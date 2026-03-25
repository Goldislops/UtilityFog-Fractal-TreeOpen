fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_dir = std::path::PathBuf::from("proto");
    if proto_dir.exists() {
        let protos: Vec<_> = std::fs::read_dir(&proto_dir)?
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().map(|x| x == "proto").unwrap_or(false))
            .map(|e| e.path())
            .collect();
        if !protos.is_empty() {
            tonic_build::configure()
                .build_server(true)
                .build_client(true)
                .compile(&protos, &[proto_dir])?;
        }
    }

    if std::env::var("CARGO_FEATURE_CUDA").is_ok() {
        println!("cargo:rerun-if-changed=src/cuda/engram_pantry.cu");
        println!("cargo:rerun-if-changed=src/cuda/lucid_dreaming.cu");
        let cuda_root = std::env::var("CUDA_ROOT").unwrap_or_else(|_| "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.6".into());
        println!("cargo:rustc-link-search=native={}\\lib\\x64", cuda_root);
        println!("cargo:rustc-link-lib=cudart");
        println!("cargo:rustc-link-lib=cuda");
    }

    println!("cargo:rerun-if-changed=build.rs");
    Ok(())
}
