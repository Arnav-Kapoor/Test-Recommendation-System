import csv
import json
import requests
from collections import defaultdict
from urllib.parse import urlparse
import pandas as pd
import time

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════

API_URL     = "http://localhost:8000/recommend"
CSV_PATH    = "Gen_AI_Dataset.csv"
K           = 10


# ══════════════════════════════════════════════════════════════
#  URL NORMALIZER — strips prefix differences so slugs match
# ══════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    path = urlparse(url.strip()).path.rstrip("/")
    for prefix in ["/solutions/products/product-catalog/view",
                   "/products/product-catalog/view"]:
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


# ══════════════════════════════════════════════════════════════
#  LOAD CSV — group URLs by query, keep only unique queries
# ══════════════════════════════════════════════════════════════

def load_ground_truth(path: str) -> dict[str, list[str]]:
    ground_truth = defaultdict(list)
    seen_queries = []
    train=pd.read_excel('Gen_AI Dataset.xlsx',sheet_name='Train-Set')
    # train=train.drop_duplicates(subset='Query')
    for _, row in train.iterrows():
        query = row['Query']
        if query not in ground_truth:
            ground_truth[query] = []
        ground_truth[query].append(normalize_url(row['Assessment_url']))

    # Return as ordered dict of unique queries
    return ground_truth


# ══════════════════════════════════════════════════════════════
#  RECALL@K
# ══════════════════════════════════════════════════════════════

def recall_at_k(retrieved_urls: list[str], relevant_urls: list[str], k: int) -> float:
    if not relevant_urls:
        return 0.0
    top_k    = [normalize_url(u) for u in retrieved_urls[:k]]
    hits     = sum(1 for u in top_k if u in set(relevant_urls))
    return hits / len(relevant_urls)


# ══════════════════════════════════════════════════════════════
#  EVALUATE
# ══════════════════════════════════════════════════════════════

def evaluate():
    ground_truth  = load_ground_truth(CSV_PATH)
    recall_scores = []

    print(f"Unique queries: {len(ground_truth)} | K={K}\n")
    print("-" * 60)

    for i, (query, relevant_urls) in enumerate(ground_truth.items(), start=1):
        if i%3==0:
            time.sleep(62)
        print(f"[{i}] {query[:80]}...")

        try:
            response = requests.post(API_URL, json={"query": query}, timeout=180)
            response.raise_for_status()
            retrieved_urls = [rec["url"] for rec in response.json().get("recommendations", [])]
        except Exception as e:
            print(f"  Error: {e}\n")
            continue
        top_k_normalized = [normalize_url(u) for u in retrieved_urls[:K]]
        print(f"  Relevant  (normalized): {relevant_urls}")
        print(f"  Retrieved (normalized): {top_k_normalized}")

        score = recall_at_k(retrieved_urls, relevant_urls, K)
        recall_scores.append(score)
        print(f"  Recall@{K}: {score:.4f}  (hits: {round(score * len(relevant_urls))}/{len(relevant_urls)})\n")

    mean_recall = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0
    print("-" * 60)
    print(f"Mean Recall@{K}: {mean_recall:.4f}")


if __name__ == "__main__":
    evaluate()