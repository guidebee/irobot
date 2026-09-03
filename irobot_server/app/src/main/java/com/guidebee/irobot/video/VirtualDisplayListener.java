package com.guidebee.irobot.video;

import com.guidebee.irobot.control.PositionMapper;

public interface VirtualDisplayListener {
    void onNewVirtualDisplay(int displayId, PositionMapper positionMapper);
}
