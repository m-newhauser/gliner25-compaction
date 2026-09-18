from gliner2 import AutoExtractor


CHECKPOINT = "fastino/gliner2.5-base-v1"


if __name__ == "__main__":
    AutoExtractor.from_pretrained(CHECKPOINT)
    print(f"Cached {CHECKPOINT}")
