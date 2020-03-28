//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "device.hpp"
#include "util/log.hpp"

bool
device_read_info(socket_t device_socket, char *device_name, struct size *size) {
    unsigned char buf[DEVICE_NAME_FIELD_LENGTH + 4];
    int r = net_recv_all(device_socket, buf, sizeof(buf));
    if (r < DEVICE_NAME_FIELD_LENGTH + 4) {
        LOGE("Could not retrieve device information");
        return false;
    }
    // in case the client sends garbage
    buf[DEVICE_NAME_FIELD_LENGTH - 1] = '\0';
    // strcpy is safe here, since name contains at least
    // DEVICE_NAME_FIELD_LENGTH bytes and strlen(buf) < DEVICE_NAME_FIELD_LENGTH
    strcpy(device_name, (char *) buf);
    size->width = (static_cast<unsigned  char>(buf[DEVICE_NAME_FIELD_LENGTH] << 8))
                  | buf[DEVICE_NAME_FIELD_LENGTH + 1];
    size->height = (static_cast<unsigned  char>(buf[DEVICE_NAME_FIELD_LENGTH + 2] << 8))
                   | buf[DEVICE_NAME_FIELD_LENGTH + 3];
    return true;
}
