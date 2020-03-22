//
// Created by James Shen on 22/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//
unsigned int factorial(unsigned int number) {
    return number <= 1 ? number : factorial(number - 1) * number;
}