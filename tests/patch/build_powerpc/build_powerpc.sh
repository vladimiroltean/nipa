#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2026 NXP

toolchain="/toolchains/powerpc64-e5500--glibc--stable-2025.08-1"
sysroot="${toolchain}/powerpc64-buildroot-linux-gnu/sysroot"
path="$toolchain/bin"
arch="powerpc"
cross_compile="powerpc64-buildroot-linux-gnu-"
cc="ccache powerpc64-buildroot-linux-gnu-gcc --sysroot=$sysroot"
output_dir="build_powerpc/"

testpath=$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)
source "$testpath/../build_cross_compile/build_cross_compile.sh"
