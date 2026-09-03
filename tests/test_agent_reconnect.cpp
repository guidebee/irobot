//
// Regression coverage for the agent client/server connection redesign
// (src/agent/agent_controller.*, src/agent/agent_stream.*): repeated
// connect/disconnect must never leave the acceptor unable to accept a new
// client, multiple simultaneous clients must all see broadcast traffic, and
// Stop() must return promptly even with a live, idle client connected.
//
// Drives AgentController/AgentStream directly over real loopback sockets --
// no Android device needed, since Init()/Start() on these two classes have
// no device dependency (only AgentManager's frame-building methods do).
//

#include <catch2/catch_all.hpp>
#include <atomic>
#include <cstring>

#include "agent/agent_controller.hpp"
#include "agent/agent_stream.hpp"
#include "platform/net.hpp"
#include "util/buffer_util.hpp"

using namespace irobot;

namespace
{
    // ports well away from irobot's own default agent ports (27184/27185)
    constexpr uint16_t kControlPort = 39181;
    constexpr uint16_t kVideoPort = 39182;

    socket_t Connect(uint16_t port)
    {
        socket_t s = platform::net_connect(IPV4_LOCALHOST, port);
        REQUIRE(s != INVALID_SOCKET);
        return s;
    }

    void SendControlMessage(socket_t sock, message::ControlMessageType type)
    {
        message::ControlMessage msg{};
        msg.type = type;
        auto json_str = msg.JsonSerialize();
        std::vector<unsigned char> frame(4 + json_str.size());
        util::buffer_write32be(frame.data(), (uint32_t)json_str.size());
        memcpy(frame.data() + 4, json_str.data(), json_str.size());
        int w = platform::net_send_all(sock, frame.data(), frame.size());
        REQUIRE(w == (int)frame.size());
    }

    void CountingHandler(void* entity, message::ControlMessage* /*msg*/)
    {
        static_cast<std::atomic<int>*>(entity)->fetch_add(1);
    }

    message::BlobMessage MakeResolutionMessage(uint64_t width, uint64_t height)
    {
        message::BlobMessage msg{};
        msg.type = message::BLOB_MSG_TYPE_RESOLUTION;
        msg.id = 0;
        msg.count = 1;
        msg.buffers[0].data = (unsigned char*)SDL_malloc(16);
        util::buffer_write64be(msg.buffers[0].data, width);
        util::buffer_write64be(msg.buffers[0].data + 8, height);
        msg.buffers[0].length = 0;
        msg.total_length = 16;
        return msg;
    }
}

TEST_CASE("agent controller survives repeated connect/disconnect", "[agent][control]")
{
    platform::net_init();
    socket_t control_server = platform::listen_on_port(kControlPort, 16);
    REQUIRE(control_server != INVALID_SOCKET);

    std::atomic<int> received{0};
    agent::AgentController controller{};
    REQUIRE(controller.Init(control_server, CountingHandler, &received));
    REQUIRE(controller.Start());

    // repeatedly connect, send one message, then disconnect abruptly -- this
    // is the exact sequence that used to wedge the acceptor (see the data
    // race described in agent_controller.cpp's ControlSession comment)
    for (int i = 0; i < 30; i++)
    {
        socket_t c = Connect(kControlPort);
        SendControlMessage(c, message::CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON);
        platform::net_close(c);
    }

    // the real assertion: the acceptor must still be able to take a new
    // connection after all that churn, and a message sent on it must still
    // be forwarded to the handler
    socket_t final_client = Connect(kControlPort);
    SendControlMessage(final_client, message::CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON);

    // give the reader thread a moment to process the last write before we
    // assert the handler ran (all 31 sends should eventually be counted)
    for (int i = 0; i < 100 && received.load() < 31; i++)
    {
        SDL_Delay(10);
    }
    REQUIRE(received.load() == 31);

    platform::net_close(final_client);

    // matches AgentManager::Stop()'s order: close the listener first so the
    // acceptor thread's blocking accept() unblocks, then tear down sessions
    platform::close_socket(&control_server);
    controller.Stop();
    controller.Join();
    controller.Destroy();
}

TEST_CASE("agent controller broadcasts to multiple simultaneous clients", "[agent][control]")
{
    platform::net_init();
    socket_t control_server = platform::listen_on_port(kControlPort, 16);
    REQUIRE(control_server != INVALID_SOCKET);

    std::atomic<int> received{0};
    agent::AgentController controller{};
    REQUIRE(controller.Init(control_server, CountingHandler, &received));
    REQUIRE(controller.Start());

    socket_t c1 = Connect(kControlPort);
    socket_t c2 = Connect(kControlPort);
    socket_t c3 = Connect(kControlPort);
    SDL_Delay(50); // let the acceptor register all three sessions

    message::ControlMessage out{};
    out.type = message::CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON;
    REQUIRE(controller.PushMessage(&out));

    // each client should receive the same [4-byte length][JSON] frame
    for (socket_t c : {c1, c2, c3})
    {
        unsigned char len_buf[4];
        REQUIRE(platform::net_recv_all(c, len_buf, 4) == 4);
        uint32_t len = util::buffer_read32be(len_buf);
        std::vector<unsigned char> payload(len);
        REQUIRE(platform::net_recv_all(c, payload.data(), len) == (ssize_t)len);
    }

    platform::net_close(c1);
    platform::net_close(c2);
    platform::net_close(c3);

    // matches AgentManager::Stop()'s order: close the listener first so the
    // acceptor thread's blocking accept() unblocks, then tear down sessions
    platform::close_socket(&control_server);
    controller.Stop();
    controller.Join();
    controller.Destroy();
}

TEST_CASE("agent controller Stop() returns promptly with a live idle client", "[agent][control]")
{
    platform::net_init();
    socket_t control_server = platform::listen_on_port(kControlPort, 16);
    REQUIRE(control_server != INVALID_SOCKET);

    std::atomic<int> received{0};
    agent::AgentController controller{};
    REQUIRE(controller.Init(control_server, CountingHandler, &received));
    REQUIRE(controller.Start());

    socket_t idle_client = Connect(kControlPort);
    SDL_Delay(50);

    platform::close_socket(&control_server);
    Uint32 t0 = SDL_GetTicks();
    controller.Stop(); // must not block on the idle client's recv()
    Uint32 elapsed = SDL_GetTicks() - t0;
    REQUIRE(elapsed < 2000);

    controller.Join();
    controller.Destroy();
    platform::net_close(idle_client);
}

TEST_CASE("agent stream broadcasts frames and catches up a late joiner", "[agent][stream]")
{
    platform::net_init();
    socket_t video_server = platform::listen_on_port(kVideoPort, 16);
    REQUIRE(video_server != INVALID_SOCKET);

    agent::AgentStream stream{};
    REQUIRE(stream.Init(video_server));
    REQUIRE(stream.Start());

    socket_t v1 = Connect(kVideoPort);
    SDL_Delay(50);

    message::BlobMessage res = MakeResolutionMessage(1080, 2400);
    REQUIRE(stream.PushMessage(&res));

    // BlobMessage::Serialize layout (src/message/blob_msg.cpp): a 40-byte
    // header (type, timestamp, id, count, total_length, each u64 BE), then
    // per buffer [length:u64][width:u64][height:u64][pixels]. The
    // resolution message has one buffer with a zero-length pixel payload,
    // so it's header(40) + length(8) + width/height(16) = 64 bytes total.
    auto read_resolution_frame = [](socket_t sock)
    {
        unsigned char header[40];
        REQUIRE(platform::net_recv_all(sock, header, 40) == 40);
        REQUIRE(util::buffer_read64be(header) == message::BLOB_MSG_TYPE_RESOLUTION);

        unsigned char len_field[8];
        REQUIRE(platform::net_recv_all(sock, len_field, 8) == 8);
        REQUIRE(util::buffer_read64be(len_field) == 0); // zero-length pixel payload

        unsigned char wh[16];
        REQUIRE(platform::net_recv_all(sock, wh, 16) == 16);
        REQUIRE(util::buffer_read64be(wh) == 1080);
        REQUIRE(util::buffer_read64be(wh + 8) == 2400);
    };

    read_resolution_frame(v1);

    // a session joining after the resolution was already broadcast should
    // still be caught up immediately (AgentStream::AddSession unicast)
    socket_t v2 = Connect(kVideoPort);
    read_resolution_frame(v2);

    platform::net_close(v1);
    platform::net_close(v2);

    // matches AgentManager::Stop()'s order: close the listener first so the
    // acceptor thread's blocking accept() unblocks, then tear down sessions
    platform::close_socket(&video_server);
    stream.Stop();
    stream.Join();
    stream.Destroy();
}
