//! yorc-zig side of the yorc-rs / yorc-zig comparison (yorc-bench),
//! for Zig 0.18.0-dev.131+41f885830.
//!
//!   zig build                          # ReleaseFast unless -Doptimize says otherwise
//!   zig build -Dlibc=true              # link libc: std.process.Init.gpa becomes malloc
//!   zig build run -- --iters 10        # build and run with arguments
//!
//! The binary is zig-out/bin/orcid-libs-bench.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    // A benchmark: ReleaseFast by default; -Doptimize=Debug etc. still work.
    const optimize = b.option(std.lang.Optimize, "optimize", "Optimization mode (default: ReleaseFast)") orelse .fast;
    const libc = b.option(bool, "libc", "Link libc, so the default allocator is malloc as in the Rust program (default: false)") orelse false;

    const yorc_dep = b.dependency("yorc", .{ .target = target, .optimize = optimize });

    const exe = b.addExecutable(.{
        .name = "orcid-libs-bench",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = if (libc) true else null,
            .imports = &.{.{ .name = "yorc", .module = yorc_dep.module("yorc") }},
        }),
    });
    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    run_cmd.addPassthruArgs();
    const run_step = b.step("run", "Run the benchmark (arguments after --)");
    run_step.dependOn(&run_cmd.step);
}
