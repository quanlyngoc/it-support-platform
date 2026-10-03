// Vỏ Tauri 2 của Phenikaa IT Monitor Desktop. Mọi nghiệp vụ nằm ở Core (gọi qua HTTPS/WSS) — phía Rust chỉ nạp plugin.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("không khởi động được ứng dụng Tauri");
}
