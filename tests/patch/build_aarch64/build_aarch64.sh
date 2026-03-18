#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2026 NXP

toolchain="/toolchains/aarch64--glibc--stable-2025.08-1"
sysroot="${toolchain}/aarch64-buildroot-linux-gnu/sysroot"
path="$toolchain/bin"
arch="arm64"
cross_compile="aarch64-buildroot-linux-gnu-"
cc="ccache aarch64-buildroot-linux-gnu-gcc --sysroot=$sysroot"
output_dir="build_aarch64/"

testpath=$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)
source "$testpath/../build_cross_compile/build_cross_compile.sh"
