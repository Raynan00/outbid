"""Quick analytics check — run on server with: docker-compose exec bot python analytics_check.py"""
import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://outbid:outbid_secret@db:5432/outbid')

    # 1. Scouts with 0 reveal credits
    zero_credits = await conn.fetchval(
        "SELECT COUNT(*) FROM users WHERE subscription_plan = 'scout' AND reveal_credits = 0"
    )
    total_scouts = await conn.fetchval(
        "SELECT COUNT(*) FROM users WHERE subscription_plan = 'scout'"
    )
    print(f"\n{'='*60}")
    print(f"SCOUTS WITH 0 REVEAL CREDITS")
    print(f"{'='*60}")
    print(f"  {zero_credits} out of {total_scouts} scouts ({round(zero_credits/max(total_scouts,1)*100, 1)}%)")

    # 2. Keyword pattern distribution (all users)
    all_keywords = await conn.fetch(
        "SELECT keywords FROM users WHERE keywords IS NOT NULL AND keywords != ''"
    )
    keyword_counts = {}
    for row in all_keywords:
        for kw in row['keywords'].split(','):
            kw = kw.strip().lower()
            if kw:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    sorted_kw = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
    print(f"\n{'='*60}")
    print(f"KEYWORD DISTRIBUTION — ALL USERS ({len(all_keywords)} users with keywords)")
    print(f"{'='*60}")
    for kw, count in sorted_kw[:30]:
        bar = '█' * min(count, 50)
        print(f"  {kw:<35} {count:>4}  {bar}")
    if len(sorted_kw) > 30:
        print(f"  ... and {len(sorted_kw) - 30} more unique keywords")

    # 3. Keyword patterns among paid users
    paid_keywords = await conn.fetch(
        "SELECT keywords FROM users WHERE subscription_plan != 'scout' AND keywords IS NOT NULL AND keywords != ''"
    )
    paid_kw_counts = {}
    for row in paid_keywords:
        for kw in row['keywords'].split(','):
            kw = kw.strip().lower()
            if kw:
                paid_kw_counts[kw] = paid_kw_counts.get(kw, 0) + 1

    sorted_paid = sorted(paid_kw_counts.items(), key=lambda x: x[1], reverse=True)
    print(f"\n{'='*60}")
    print(f"KEYWORD DISTRIBUTION — PAID USERS ({len(paid_keywords)} paid with keywords)")
    print(f"{'='*60}")
    for kw, count in sorted_paid:
        bar = '█' * min(count, 50)
        print(f"  {kw:<35} {count:>4}  {bar}")

    await conn.close()

asyncio.run(main())
