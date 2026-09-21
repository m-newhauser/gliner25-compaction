import os

from gliner2 import AutoExtractor


CHECKPOINT = os.environ.get(
    "GLINER25_CHECKPOINT", "fastino/gliner2.5-small-v1"
)


if __name__ == "__main__":
    AutoExtractor.from_pretrained(CHECKPOINT)
    print(f"Cached {CHECKPOINT}")
