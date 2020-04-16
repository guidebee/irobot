//
// Created by James Shen on 5/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch2/catch.hpp"


#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/highgui.hpp>

using namespace cv;

TEST_CASE("test opencv library", "[opencv]") {
    Mat A = Mat(3, 4, CV_32FC1);
    Mat B = Mat(4, 3, CV_32FC1);
    REQUIRE(A.rows == 3);
    REQUIRE(B.rows == 4);
}