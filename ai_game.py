"""Spec-based AI/gaming tiers. Objective spec thresholds only: no benchmark, FPS or score is invented.

S: NVIDIA RTX (or AMD Radeon RX) discrete GPU with 8GB+ VRAM - games and local AI acceleration
A: discrete GPU with less VRAM (or VRAM unknown), or a high-end integrated GPU reviewed near
   RTX 4050 class (Intel Arc B390, AMD Radeon 8060S/8050S) - entry/mid gaming and AI
B: no discrete GPU but NPU 40 TOPS+ (Copilot+ class AI PC) - AI features, weak for games
C: everything else
"""
import re

TIER_ORDER = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
TIER_LABEL = {
    'S': 'S · 외장 GPU VRAM 8GB+ (게임·로컬 AI 적합)',
    'A': 'A · 외장 GPU 입문급 또는 고성능 내장 GPU (가벼운~중간 게임·AI)',
    'B': 'B · AI PC (NPU 40TOPS+, 게임 약함)',
    'C': 'C · 내장 그래픽 (AI·게임 비권장)',
}


def gpu_info(p):
    text = ' '.join(str(p.get(k) or '') for k in ('gpu', 'name'))
    rtx = re.search(r'RTX\s*-?\s*(\d{4})', text, re.I)
    rx = re.search(r'Radeon\s*RX\s*(\d{4})', text, re.I)
    vram = re.search(r'VRAM\s*:?\s*(\d+)\s*GB', text, re.I)
    model = ('RTX' + rtx[1]) if rtx else (('RX' + rx[1]) if rx else None)
    return model, int(vram[1]) if vram else None


STRONG_IGPU = re.compile(r'Arc\s*B390|Radeon\s*80[56]0S', re.I)


# 가격비교 사이트가 그래픽을 'Intel Graphics'로만 적는 경우: 울트라 X7/X9(팬서레이크)는 Arc B390 탑재 모델
CPU_IMPLIES_B390 = re.compile(r'울트라\s*X[79]|Ultra\s*X[79]', re.I)
CPU_IMPLIES_8060S = re.compile(r'(?:AI\s*Max|AI\s*맥스)\s*(?:\+|플러스)?\s*(?:PRO\s*|프로\s*)?(395|392|388)', re.I)
CPU_IMPLIES_8050S = re.compile(r'(?:AI\s*Max|AI\s*맥스)\s*(?:\+|플러스)?\s*(?:PRO\s*|프로\s*)?(390|385)', re.I)


def strong_igpu(p):
    m = STRONG_IGPU.search(' '.join(str(p.get(k) or '') for k in ('gpu', 'name')))
    if m:
        return m[0]
    cpu = str(p.get('cpu') or '')
    if CPU_IMPLIES_B390.search(cpu):
        return 'Arc B390'
    if CPU_IMPLIES_8060S.search(cpu):
        return 'Radeon 8060S'
    if CPU_IMPLIES_8050S.search(cpu):
        return 'Radeon 8050S'
    return None


def npu_tops(p):
    m = re.search(r'(\d+)\s*TOPS', str(p.get('cpu') or ''), re.I)
    return int(m[1]) if m else None


def tier(p):
    model, vram = gpu_info(p)
    if model:
        return 'S' if (vram or 0) >= 8 else 'A'
    if strong_igpu(p):
        return 'A'
    tops = npu_tops(p)
    return 'B' if tops is not None and tops >= 40 else 'C'


def vram_warning(p):
    """외장 GPU인데 VRAM 4GB 이하면 로컬 AI용으로 부족 표시 (후보에서 빼지는 않음)."""
    model, vram = gpu_info(p)
    if model and vram is not None and vram <= 4:
        return 'AI용 VRAM 부족(' + str(vram) + 'GB)'
    return None


def describe(p):
    model, vram = gpu_info(p)
    t = tier(p)
    bits = [TIER_LABEL[t]]
    if model:
        bits.append(model + (' ' + str(vram) + 'GB' if vram else ''))
    elif strong_igpu(p):
        bits.append('내장 ' + strong_igpu(p) + ' (RTX4050급 근접 리뷰, CUDA 미지원)')
    if vram_warning(p):
        bits.append('⚠ ' + vram_warning(p))
    tops = npu_tops(p)
    if tops is not None:
        bits.append('NPU ' + str(tops) + 'TOPS')
    return ' · '.join(bits)


def allowed(p, min_tier='A'):
    return TIER_ORDER[tier(p)] <= TIER_ORDER.get(min_tier, 1)
