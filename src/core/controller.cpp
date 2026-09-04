//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "controller.hpp"

#include <cassert>
#include <cstring>

#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot
{
    bool Controller::Init(socket_t control_socket)
    {
        cbuf_init(&this->queue);
        if (!this->receiver.Init(control_socket))
        {
            return false;
        }
        bool initialized = Actor::Init();
        if (!initialized)
        {
            this->receiver.Destroy();
            return false;
        }
        this->control_socket = control_socket;
        this->stopped = false;
        return true;
    }

    void Controller::Stop()
    {
        Actor::Stop();
        this->receiver.Stop();
    }

    void Controller::Destroy()
    {
        Actor::Destroy();
        message::ControlMessage msg{};
        while (cbuf_take(&this->queue, &msg))
        {
            msg.Destroy();
        }
        this->receiver.Destroy();
    }

    bool Controller::PushMessage(
        const message::ControlMessage* msg)
    {
        // ControlMessage's INJECT_TEXT/SET_CLIPBOARD variants own a heap
        // string (freed by Destroy()). cbuf_push() below copies the struct
        // by value into this->queue, but the caller (AgentController's
        // reader thread, for agent-forwarded messages) destroys its own
        // *msg right after this call returns -- a shallow copy would leave
        // the queued copy holding an already-freed pointer, which becomes a
        // use-after-free when this queue is later serialized, and a
        // double-free when the queued copy is Destroy()'d in turn. Deep-copy
        // the owned string here so the queued copy has its own independent
        // allocation.
        message::ControlMessage copy = *msg;
        switch (copy.type)
        {
        case message::CONTROL_MSG_TYPE_INJECT_TEXT:
            if (msg->inject_text.text)
            {
                size_t len = strlen(msg->inject_text.text);
                copy.inject_text.text = (char*)SDL_malloc(len + 1);
                if (!copy.inject_text.text)
                {
                    return false;
                }
                memcpy(copy.inject_text.text, msg->inject_text.text, len + 1);
            }
            break;
        case message::CONTROL_MSG_TYPE_SET_CLIPBOARD:
            if (msg->set_clipboard.text)
            {
                size_t len = strlen(msg->set_clipboard.text);
                copy.set_clipboard.text = (char*)SDL_malloc(len + 1);
                if (!copy.set_clipboard.text)
                {
                    return false;
                }
                memcpy(copy.set_clipboard.text, msg->set_clipboard.text, len + 1);
            }
            break;
        default:
            break;
        }

        util::mutex_lock(this->mutex);
        bool was_empty = cbuf_is_empty(&this->queue);
        bool res = cbuf_push(&this->queue, copy);
        if (was_empty)
        {
            util::cond_signal(this->thread_cond);
        }
        util::mutex_unlock(this->mutex);
        if (!res)
        {
            // queue was full: the copy was never stored, so we still own
            // (and must free) the allocation made above
            copy.Destroy();
        }
        return res;
    }

    bool Controller::ProcessMessage(
        message::ControlMessage* msg)
    {
        unsigned char serialized_msg[CONTROL_MSG_SERIALIZED_MAX_SIZE];
        int length = msg->Serialize(serialized_msg);
        if (!length)
        {
            // an unserializable message type (e.g. CONTROL_MSG_TYPE_UNKNOWN)
            // is not a socket error: drop it and keep the controller alive,
            // rather than treating it as a fatal write failure
            LOGW("Could not serialize control message (type=%d), dropping it",
                 (int)msg->type);
            return true;
        }
        int w = platform::net_send_all(this->control_socket,
                                       serialized_msg, length);
        return w == length;
    }

    int Controller::RunController(void* data)
    {
        auto* controller = static_cast<Controller*>(data);
        for (;;)
        {
            util::mutex_lock(controller->mutex);
            while (!controller->stopped && cbuf_is_empty(&controller->queue))
            {
                util::cond_wait(controller->thread_cond, controller->mutex);
            }
            if (controller->stopped)
            {
                // stop immediately, do not process further msgs
                util::mutex_unlock(controller->mutex);
                break;
            }
            message::ControlMessage msg{};
            bool non_empty = cbuf_take(&controller->queue, &msg);
            assert(non_empty);
            (void)non_empty;
            util::mutex_unlock(controller->mutex);
            bool ok = controller->ProcessMessage(&msg);
            msg.Destroy();
            if (!ok)
            {
                LOGD("Could not write msg to socket");
                break;
            }
        }
        return 0;
    }

    bool Controller::Start()
    {
        LOGD("Starting controller thread");
        this->thread = SDL_CreateThread(RunController, "controller",
                                        this);
        if (!this->thread)
        {
            LOGC("Could not start controller thread");
            return false;
        }
        if (!this->receiver.Start())
        {
            this->Stop();
            SDL_WaitThread(this->thread, nullptr);
            return false;
        }
        return true;
    }


    void Controller::Join()
    {
        Actor::Join();
        this->receiver.Join();
    }
}