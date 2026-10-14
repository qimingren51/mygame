fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    // 构建脚本在宿主机运行，必须按 Cargo 的目标系统判断，兼容交叉编译。
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        const ICON: &str = "../../packaging/windows/lantern.ico";
        const MANIFEST: &str = "../../packaging/windows/lantern.manifest";
        println!("cargo:rerun-if-changed={ICON}");
        println!("cargo:rerun-if-changed={MANIFEST}");

        // winresource 同时从 Cargo 版本变量生成数值 FILEVERSION / PRODUCTVERSION。
        winresource::WindowsResource::new()
            .set_icon(ICON)
            .set_manifest_file(MANIFEST)
            .set("ProductName", "提灯夜行")
            .set("FileDescription", "提灯夜行")
            .set("OriginalFilename", "lantern.exe")
            .set("FileVersion", env!("CARGO_PKG_VERSION"))
            .set("ProductVersion", env!("CARGO_PKG_VERSION"))
            .compile_for("lantern")
            .expect("编译 Windows EXE 资源失败");
    }
}
