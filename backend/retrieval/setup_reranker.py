"""One-time, explicit provisioning for the optional local cross-encoder."""

from huggingface_hub import snapshot_download

from retrieval.reranker import RERANKER_DIR, RERANKER_MODEL_NAME


def main() -> None:
    RERANKER_DIR.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=RERANKER_MODEL_NAME,
        local_dir=str(RERANKER_DIR),
    )
    print(f"Cross-encoder ready at {RERANKER_DIR}")


if __name__ == "__main__":
    main()
