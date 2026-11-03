// Punto de entrada de la app de escritorio.
// La lógica del asistente vive en el núcleo Python (core/); esta capa solo muestra la interfaz.
// En el sprint S8 el núcleo se empaquetará como "sidecar" y Tauri lo lanzará automáticamente.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("error al iniciar la app de Tauri");
}
