"""重算全部交易与待确认行的 merchant_norm 与指纹。

**改动 app/services/normalize.py 之后必须运行**：指纹由规范化结果算出，
规则一变，库里旧记录的指纹就与新导入的同一笔对不上——判重会从「重复」
退化成「可能重复」甚至漏判。商家记忆（merchant_memory）的键同样需要迁移。

用法（停掉服务后运行）：
    backend/.venv/Scripts/python.exe scripts/renormalize.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.models import MerchantMemory, StagedTransaction, Transaction  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.normalize import make_fingerprint, normalize_merchant  # noqa: E402


def main() -> None:
    db = SessionLocal()
    changed_txn = changed_staged = changed_mem = merged_mem = 0
    try:
        for t in db.execute(select(Transaction)).scalars():
            norm = normalize_merchant(t.merchant_raw)
            fp = make_fingerprint(t.date, t.direction.value, t.amount, norm)
            if norm != t.merchant_norm or fp != t.fingerprint:
                t.merchant_norm, t.fingerprint = norm, fp
                changed_txn += 1

        for s in db.execute(select(StagedTransaction)).scalars():
            norm = normalize_merchant(s.merchant_raw)
            fp = (
                make_fingerprint(s.date, s.direction.value, s.amount, norm)
                if (s.date and s.amount is not None and s.direction)
                else ""
            )
            if norm != s.merchant_norm or fp != s.fingerprint:
                s.merchant_norm, s.fingerprint = norm, fp
                changed_staged += 1

        # 商家记忆按 (user_id, merchant_norm) 唯一；两个旧键归一到同一新键时合并计数
        seen: dict[tuple[int, str], MerchantMemory] = {}
        for m in db.execute(select(MerchantMemory)).scalars():
            # merchant_norm 是规范化结果，再规范化一次应是幂等的；不是则说明规则变了
            new_norm = normalize_merchant(m.merchant_norm)
            key = (m.user_id, new_norm)
            if key in seen:
                keeper = seen[key]
                keeper.hit_count += m.hit_count
                if m.last_seen_at > keeper.last_seen_at:
                    keeper.category_id, keeper.last_seen_at = m.category_id, m.last_seen_at
                db.delete(m)
                merged_mem += 1
                continue
            if new_norm != m.merchant_norm:
                m.merchant_norm = new_norm
                changed_mem += 1
            seen[key] = m

        db.commit()
    finally:
        db.close()

    print(f"交易：更新 {changed_txn} 条")
    print(f"待确认行：更新 {changed_staged} 条")
    print(f"商家记忆：更新 {changed_mem} 条，合并 {merged_mem} 条")


if __name__ == "__main__":
    main()
