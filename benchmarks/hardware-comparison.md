# Hardware Comparison: External TB5 vs Internal NVMe

Measured on same Mac Mini M4 Pro, same model, same code. Same day to control for thermal/system variables.

## Hardware

| Component | Internal | External |
|---|---|---|
| Controller | Apple M4 Pro integrated | WD Black SN850X |
| Form factor | Embedded | 2.5" NVMe in Acasis TB5 enclosure |
| Capacity | 462 GB | 2 TB |
| Interface | Apple proprietary (M.2-like) | USB4/TB5 (JHL9480 chip) |
| Sustained read (rated) | ~7 GB/s | ~7.3 GB/s |
| Random 4K read (rated) | Not published | ~90 MB/s |
| Price | Included with Mac | ~$180 SSD + $250 enclosure |

## Measurements

### Sequential read throughput

Plain large file read test:

```bash
# 100GB file read
time dd if=large_file of=/dev/null bs=1m count=100
```

| Storage | Time | Throughput |
|---|---|---|
| Internal | 14.7s | 6.8 GB/s |
| External TB5 | 16.1s | 6.2 GB/s |

Both near saturation of their respective buses. **Sequential reads similar.**

### MoE inference (real workload)

Flash-MoE with Qwen3.5-397B-A17B-4bit, 20-token generation:

| Storage | tok/s | per-layer ms | expert_io ms |
|---|---|---|---|
| External TB5 SN850X | 5.41 | 3.009 | 1.606 |
| Internal NVMe | 3.17 | 3.632 | 2.012 |
| Difference | **-41%** | +21% | **+25%** |

**Internal is significantly slower on MoE-style random access.** expert_io is the bottleneck phase (SSD reads for selected experts).

### TTFT (time to first token)

| Storage | TTFT (1-token prompt) | TTFT (19-token prompt) |
|---|---|---|
| External TB5 | 2.19s | ~3.5s |
| Internal | 5.17s (cold) / 1.02s (warm) | ~7.2s (cold) |

First-time loading on internal is slower (cold page cache). Warm performance comparable.

### Long generation (page cache warmed)

Korean 200-token generation, cache_entries 20000, --predict:

| Storage | tok/s | Cache hit rate | Notes |
|---|---|---|---|
| External | ~6 tok/s | High | Produced garbage output ⚠️ |
| Internal | 8.76 tok/s | 93.5% | Same issue |

Both showed high cache hit with pread errors (see `cache-tuning-results.md`). Not a reliable comparison.

## Stability

This is where the hardware comparison inverts.

### External SSD detach events (48 hours)

| Period | Detach count | Notes |
|---|---|---|
| Day 1 (Phase 7) | 2 | Overnight detach during sleep |
| Day 2 (Phase 9) | Frequent | Fighting with keepalive |

Root causes:
- Acasis TB5 enclosure has 5-min idle timeout (not configurable)
- macOS Sandbox TCC blocks touch/write from unsigned scripts
- Keepalive ran but denied by system → enclosure thought idle → disconnect

### Internal NVMe

| Period | Issues |
|---|---|
| Day 2 onwards | Zero |

No detach, no instability, no intervention needed.

## Effective throughput (realistic)

Factoring in stability:

| Setup | Raw tok/s | Uptime | Effective tok/s |
|---|---|---|---|
| External (unreliable) | 5.41 | ~60% (detaches) | ~3.2 |
| Internal (stable) | 3.17 | 99%+ | 3.1 |

**Basically equivalent** when stability considered. External only wins if you fight the keepalive battle successfully (we didn't).

## Cost analysis

### External setup

- WD SN850X 2TB: $180
- Acasis TB5 enclosure: $250
- **Total: $430**

### Internal (already owned)

- Part of Mac Mini purchase
- **Marginal cost: $0**

### Value

External setup's value in our case:
- ❌ Didn't solve stability problem
- ✓ Provides model backup (protection against internal SSD failure)
- ✓ Portable (can move to another machine)
- ✓ 2TB usable for other storage needs

$430 for backup + expansion storage is reasonable. As primary MoE inference storage: not worth the instability.

## Recommendations

### For MoE inference on Mac

**Use internal SSD.** The speed penalty (~40% on MoE random reads) is real but stability is more valuable.

If internal is too small:
- External as backup only (not hot storage)
- Or Mac Studio/Mac Pro with larger internal options
- Or wait for better TB5 enclosures with no idle timeout

### For general workloads

External TB5 SSDs are fine for:
- Video editing (sequential reads dominate)
- Photo libraries
- Sequential batch processing
- Not continuously online

They're unreliable for:
- Always-on services
- Random-access workloads
- Anything relying on mmap stability
- Database hot storage

### For reproducing this project

If you have M4 Pro+ with 500GB+ internal SSD, use internal. Simpler, stable, 3-5 tok/s is sufficient.

If you have smaller internal (256GB), external becomes necessary. Budget for:
- Best available TB5 enclosure (read reviews for idle timeout)
- Consider external enclosure with active cooling
- Test detach behavior 48+ hours before committing

## What I'd buy differently

If starting over:

1. **Mac Mini with 1TB internal** instead of 462GB
   - Would fit model comfortably
   - Skip external entirely
   - Net cost similar ($200 Apple upgrade vs $430 external)

2. **If external necessary**: Acasis TB5 was among fastest but had idle timeout. Research alternatives:
   - Check for enclosures without power management
   - Check reviews for "always on" behavior
   - Consider active-cooled enclosures for sustained loads

## Related

- `cache-tuning-results.md` — why raw speed doesn't matter if cache causes errors
- `lessons/what-failed.md#3` — detach failure mode details
- `docs/07-internal-migration.md` — migration story
