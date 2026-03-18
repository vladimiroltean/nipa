#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2026 NXP

toolchain="/toolchains/riscv64-lp64d--glibc--stable-2025.08-1"
sysroot="${toolchain}/riscv64-buildroot-linux-gnu/sysroot"
path="$toolchain/bin"
arch="riscv"
cross_compile="riscv64-buildroot-linux-gnu-"
cc="ccache riscv64-buildroot-linux-gnu-gcc --sysroot=$sysroot"
output_dir="build_riscv/"

testpath=$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)
source "$testpath/../build_cross_compile/build_cross_compile.sh"
