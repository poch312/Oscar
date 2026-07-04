"""Train oscar.tamper.model.TwoStreamTamperNet on CASIA 2.0.

This produces the Fase 0 placeholder checkpoint (natural-photo-splicing
domain, not fine-tuned on real actas — see docs/architecture.md risks on
domain transfer). Fase 2 re-runs this same script against a real/synthetic
acta-domain dataset once one exists.

Usage: python scripts/train_tamper_model.py --data data/casia/casia2 --out models/casia_pretrained.pt
"""

from __future__ import annotations

import argparse

import torch
from torch import nn, optim
from torch.utils.data import DataLoader, random_split

from oscar.tamper.dataset import CasiaTamperDataset
from oscar.tamper.model import TwoStreamTamperNet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default="models/casia_pretrained.pt")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    dataset = CasiaTamperDataset(args.data)
    val_size = max(int(0.1 * len(dataset)), 1)
    train_set, val_set = random_split(dataset, [len(dataset) - val_size, val_size])
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TwoStreamTamperNet().to(device)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.BCEWithLogitsLoss()

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        for semantic, noise, labels in train_loader:
            semantic, noise, labels = semantic.to(device), noise.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(semantic, noise)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(labels)

        model.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for semantic, noise, labels in val_loader:
                semantic, noise, labels = semantic.to(device), noise.to(device), labels.to(device)
                proba = model.predict_proba(semantic, noise)
                correct += ((proba >= 0.5).float() == labels).sum().item()
                total += len(labels)

        print(
            f"epoch {epoch + 1}/{args.epochs} "
            f"train_loss={total_loss / len(train_set):.4f} val_acc={correct / total:.4f}"
        )

    torch.save(model.state_dict(), args.out)
    print(f"Checkpoint guardado en {args.out}")


if __name__ == "__main__":
    main()
