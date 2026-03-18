#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2026 NXP

toolchain="/toolchains/armv7-eabihf--glibc--stable-2025.08-1"
sysroot="${toolchain}/arm-buildroot-linux-gnueabihf/sysroot"
path="$toolchain/bin"
arch="arm"
cross_compile="arm-buildroot-linux-gnueabihf-"
cc="ccache arm-buildroot-linux-gnueabihf-gcc --sysroot=$sysroot"
output_dir="build_armv7/"

testpath=$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)
source "$testpath/../build_cross_compile/build_cross_compile.sh"
