# Phase 1-2: Environment + External SSD Setup

**Date**: 2026-04-23 (early morning)
**Duration**: ~2-3 hours
**Outcome**: Hardware ready, SSD formatted and benchmarked

## Hardware inventory

### Mac Mini M4 Pro
- **CPU**: M4 Pro (12-core CPU, 16-core GPU)
- **RAM**: 64GB unified memory
- **Internal SSD**: 462GB (out of 512GB reported)
- **macOS**: 15.x (Sequoia)
- **Thermal**: Passive cooled, ambient ~23°C
- **Location**: Clinic office, always-on, wired Ethernet

### External SSD Stack
- **SSD**: WD Black SN850X 2TB (NVMe Gen4 M.2)
- **Enclosure**: Acasis TB5 (JHL9480 chip, active cooling fan)
- **Cable**: Included Thunderbolt 5 cable (40Gbps capable)
- **Connection**: Direct to Mac Mini TB5 port

### Total specs relevant to Flash-MoE
- 64GB unified memory (for page cache + expert LRU)
- Fast SSD random read (for expert streaming)
- Stable I/O (for long-running inference)

## Initial system check

```bash
# macOS version
sw_vers
# ProductName: macOS
# ProductVersion: 15.x

# CPU info
sysctl -n machdep.cpu.brand_string
# Apple M4 Pro

# Memory
sysctl -n hw.memsize
# 68719476736 (64GB)

# Storage
diskutil list
df -h /
```

Everything as expected.

## External SSD preparation

### Mount check

Plugged in, waited for OS recognition:

```bash
diskutil list external
```

```
/dev/disk5 (external, physical):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      GUID_partition_scheme                        *2.0 TB     disk5
   1:                        EFI EFI                     209.7 MB   disk5s1
   2:                 Apple_APFS Container disk6         2.0 TB     disk5s2

/dev/disk6 (synthesized):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      APFS Container Scheme -                      +2.0 TB     disk6
   1:                APFS Volume FlashMoE                447.0 GB   disk6s1
```

Already APFS formatted. Good.

### Alternatively: reformat

If your external SSD isn't APFS:

```bash
# Identify disk
diskutil list external

# Erase + create APFS (DESTROYS DATA)
diskutil eraseDisk APFS "FlashMoE" /dev/disk5

# Verify
diskutil info /Volumes/FlashMoE
```

APFS chosen because:
- Native macOS support
- Copy-on-write (safer than HFS+)
- Better TRIM support
- Standard for modern Apple Silicon

### Permission setup

External volumes may have restrictions:

```bash
# Check current ownership
ls -la /Volumes/FlashMoE

# If needed, disable "ignore ownership"
sudo chown -R migi:staff /Volumes/FlashMoE/
```

Usually works out of the box on fresh format.

## Benchmarking

### Sequential write

```bash
# Write 10GB random data
dd if=/dev/urandom of=/Volumes/FlashMoE/test_write.bin bs=1m count=10000
```

**Result**: ~3.5-4.0 GB/s sustained
- Apple's TB5 implementation saturates around 4 GB/s for sustained writes
- Burst can be higher but sustained is more meaningful for Flash-MoE

### Sequential read

```bash
# Clear page cache
sudo purge

# Read the file back
time dd if=/Volumes/FlashMoE/test_write.bin of=/dev/null bs=1m
```

**Result**: ~6.0-7.0 GB/s sustained
- TB5 theoretical max: ~7.5 GB/s
- Very close to theoretical limit
- Faster than internal in this benchmark

### Random 4K read (more relevant for MoE)

```bash
# Create test file with random data
dd if=/dev/urandom of=/Volumes/FlashMoE/random_test.bin bs=1m count=1000

# Random read pattern
# (using fio if available, or custom script)
fio --name=random_read --rw=randread --bs=4k --size=1g \
    --filename=/Volumes/FlashMoE/random_test.bin \
    --direct=1 --iodepth=32 --runtime=30
```

**Result**: ~90 MB/s random 4K read

This is what matters for MoE streaming. Each expert file read is sort of in-between sequential and random:
- Sequential within expert (reading ~7MB per expert)
- Random across experts (different experts per token)

Effective throughput: somewhere between 90 MB/s and 7 GB/s depending on pattern.

### Verdict

SSD performance adequate for Flash-MoE expectations. TB5 interface not a bottleneck (could saturate PCIe Gen5 chip).

## Cleanup benchmark files

```bash
rm /Volumes/FlashMoE/test_write.bin
rm /Volumes/FlashMoE/random_test.bin

df -h /Volumes/FlashMoE  # Confirm space freed
```

## System optimizations

### Disable spotlight indexing on SSD

Indexing 200GB+ of MoE weights serves no purpose and can cause I/O contention:

```bash
sudo mdutil -i off /Volumes/FlashMoE
```

Verify:
```bash
mdutil -s /Volumes/FlashMoE
# Indexing disabled.
```

### Disable Time Machine (if enabled)

```bash
sudo tmutil addexclusion /Volumes/FlashMoE
```

Time Machine backing up 200GB of model files overnight would be wasteful.

### Power settings

```bash
# Prevent sleep (we need always-on)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0

# Verify
pmset -g
```

**Note**: These don't prevent the external enclosure's internal idle timeout (hardware-level), which caused issues later.

### Keepalive consideration

At this point, we assumed keepalive scripts would be sufficient to prevent detach. Wrong. See `docs/07-internal-migration.md` for the full Sandbox/TCC battle. But during Phase 1-2 setup, not yet a known issue.

## Development tooling

### Homebrew

```bash
# Already installed typically; verify
which brew
brew --version

# Update
brew update
```

### Python

Used system Python + virtual environment:

```bash
# Python 3.14 via Homebrew
brew install python@3.14

# Create venv for project
python3.14 -m venv ~/flashmoe_venv

# Activate
source ~/flashmoe_venv/bin/activate

# Verify
which python  # → ~/flashmoe_venv/bin/python
python --version  # → Python 3.14.2 or similar
```

### Essential packages

```bash
pip install --upgrade pip
pip install huggingface-hub aria2
pip install safetensors  # For reading model files
```

### aria2c for downloads

```bash
brew install aria2
aria2c --version
```

aria2 supports parallel chunked downloads, essential for 224GB model grab.

### Git

Pre-installed on macOS, but verify:

```bash
git --version
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

## Directory structure

Created initial layout:

```bash
mkdir -p /Volumes/FlashMoE/{flash-moe,flash-moe-venv,models,staging}

# flash-moe: Flash-MoE repo
# flash-moe-venv: Alternative venv (not used, kept ~/flashmoe_venv)
# models: target for downloaded model
# staging: temporary holding area for chunks
```

On internal:
```bash
mkdir -p ~/flashmoe_logs
```

For logs later.

## Verified state after Phase 1-2

- [x] Mac Mini M4 Pro operational, 64GB RAM confirmed
- [x] External 2TB SSD formatted APFS, ~447GB initial free (quickly filled)
- [x] TB5 connection measured at 6+ GB/s sequential read
- [x] Spotlight + Time Machine disabled on external
- [x] Sleep prevention configured
- [x] Python 3.14 + venv ready
- [x] aria2c installed
- [x] Directory structure created

Ready to clone Flash-MoE and start building.

## Time budget

- Hardware setup + unboxing: 30 min
- macOS checks: 15 min
- SSD benchmarking: 30 min
- System optimizations: 15 min
- Development tooling: 20 min
- Directory setup: 5 min
- **Total: ~2 hours**

Could be faster if familiar with macOS dev setup; this was my first time doing Apple Silicon AI work at scale.

## Files referenced

- `benchmarks/hardware-comparison.md` — Detailed SSD measurements
- `lessons/what-failed.md#3` — Why external SSD became a problem later
- `docs/07-internal-migration.md` — Migrating away from external

## Lessons for this phase

1. **Don't skip benchmarks.** 5 minutes of `dd` tests tells you if hardware meets expectations.
2. **Disable Spotlight on model volumes.** Indexing 200GB is useless + uses I/O.
3. **Don't trust `pmset` for external enclosures.** Hardware-level idle timeouts are invisible to OS.
4. **Python venv per project.** Avoids system Python pollution.
5. **Plan for backup directory.** We later copied 200GB to internal; having space allocated saves time.
