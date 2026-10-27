#!/usr/bin/env python3
"""
dicom2stl_osso.py - Converte uma série DICOM (TC ou CBCT) em STL contendo só o osso.

Uso básico:
    python dicom2stl_osso.py PASTA_DICOM saida.stl

Opções úteis:
    --limiar 400        limiar manual (HU na TC médica; valor bruto na CBCT)
    --limiar-max 2000   exclui voxels acima disso (metal, marcadores, artefatos)
    --auto              limiar automático (Otsu tecido/osso nos voxels fora do ar)  [padrão]
    --info              só mostra estatísticas do volume para ajudar a escolher o limiar
    --ilhas 1           mantém as N maiores regiões conectadas (0 = mantém tudo)
    --suavizar 10       iterações de suavização Taubin (0 = desliga)
    --reduzir 0.5       fração de triângulos a remover (0.5 = metade; 0 = não reduz)
    --reamostrar 0.3    reamostra para voxel isotrópico (mm) antes de segmentar
    --origem-zero       canto do volume em (0,0,0), sem origem/direção DICOM (Blue Sky Plan importa assim)

Dependências:
    pip install SimpleITK scikit-image trimesh numpy fast-simplification
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import trimesh
from skimage import measure
from skimage.filters import threshold_otsu


# ---------------------------------------------------------------- leitura
def ler_serie(pasta: Path) -> sitk.Image:
    """Lê a maior série DICOM da pasta (busca em subpastas também)."""
    reader = sitk.ImageSeriesReader()
    melhores = []
    for sub in [pasta, *[p for p in pasta.rglob("*") if p.is_dir()]]:
        for sid in reader.GetGDCMSeriesIDs(str(sub)) or []:
            arquivos = reader.GetGDCMSeriesFileNames(str(sub), sid)
            melhores.append((len(arquivos), sid, arquivos))
    if not melhores:
        sys.exit(f"Nenhuma série DICOM encontrada em {pasta}")
    melhores.sort(reverse=True)
    n, sid, arquivos = melhores[0]
    if len(melhores) > 1:
        print(f"[i] {len(melhores)} séries encontradas; usando a maior ({n} fatias).")
    reader.SetFileNames(arquivos)
    img = reader.Execute()  # aplica RescaleSlope/Intercept -> HU quando houver
    return sitk.Cast(img, sitk.sitkFloat32)


def info(img: sitk.Image):
    arr = sitk.GetArrayViewFromImage(img)
    sp = img.GetSpacing()
    print(f"Dimensões (x,y,z): {img.GetSize()}  |  voxel (mm): "
          f"{sp[0]:.3f} x {sp[1]:.3f} x {sp[2]:.3f}")
    obj = arr[arr > AR]
    print(f"Ar (<= {AR:.0f}): {100 * (1 - obj.size / arr.size):.1f}% do volume  |  "
          f"máximo: {arr.max():.0f}  |  voxels > 2000 (metal provável): {(arr > 2000).sum():,}")
    pcts = [5, 25, 50, 75, 95, 99, 99.9]
    print(f"Percentis de intensidade fora do ar (> {AR:.0f}):")
    for p, v in zip(pcts, np.percentile(obj, pcts)):
        print(f"  P{p:<5} {v:10.1f}")
    print("Histograma acima de -900 (bins de 100; vale entre picos = limiar candidato):")
    h, bordas = np.histogram(arr, bins=np.arange(-900, min(arr.max(), 4000) + 100, 100))
    for n, b in zip(h, bordas[:-1]):
        if n:
            print(f"  {b:6.0f} {n:11,d} {'#' * int(40 * n / h.max())}")
    try:
        t = limiar_auto(arr)
        print(f"Limiar automático sugerido (Otsu fora do ar): {t:.1f}")
    except Exception as e:  # noqa: BLE001
        print(f"Multi-Otsu falhou: {e}")


# ---------------------------------------------------------------- segmentação
AR = -300.0  # ponytail: corte fixo de ar em HU (i-CAT entrega HU); CBCT em valor bruto precisa de outro corte


def limiar_auto(arr: np.ndarray) -> float:
    """Otsu 2 classes (tecido mole / osso) só nos voxels fora do ar.
    Multi-Otsu no volume inteiro cai no ar quando >90% do campo é ar (CBCT dental)."""
    amostra = arr[arr > AR]
    if amostra.size == 0:
        sys.exit("Volume só tem ar (nada acima de -300). Confira a série ou use --limiar.")
    if amostra.size > 5_000_000:
        amostra = np.random.default_rng(0).choice(amostra, 5_000_000, replace=False)
    return float(threshold_otsu(amostra))


def segmentar(img: sitk.Image, limiar: float, limiar_max: float, ilhas: int) -> sitk.Image:
    mask = sitk.BinaryThreshold(img, lowerThreshold=limiar, upperThreshold=limiar_max,
                                insideValue=1, outsideValue=0)
    # fecha pequenos buracos e remove ruído pontual
    mask = sitk.BinaryMorphologicalClosing(mask, [1, 1, 1])
    mask = sitk.BinaryMorphologicalOpening(mask, [1, 1, 1])
    if ilhas > 0:
        cc = sitk.RelabelComponent(sitk.ConnectedComponent(mask), sortByObjectSize=True)
        mask = sitk.BinaryThreshold(cc, 1, ilhas, 1, 0)
    return mask


# ---------------------------------------------------------------- malha
def gerar_malha(mask: sitk.Image, origem_zero: bool = False) -> trimesh.Trimesh:
    arr = sitk.GetArrayFromImage(mask).astype(np.uint8)  # ordem z,y,x
    if arr.sum() == 0:
        sys.exit("Segmentação vazia: limiar alto demais. Rode com --info e ajuste --limiar.")
    arr = np.pad(arr, 1)  # garante malha fechada nas bordas
    sx, sy, sz = mask.GetSpacing()
    verts, faces, _, _ = measure.marching_cubes(arr, level=0.5, spacing=(sz, sy, sx))
    verts -= np.array([sz, sy, sx])          # desfaz o padding
    verts = verts[:, ::-1]                   # (z,y,x) -> (x,y,z) em mm
    # ponytail: --origem-zero = índice x espaçamento, como o Blue Sky Plan importa; testado só com direção identidade (i-CAT)
    D = np.eye(3) if origem_zero else np.array(mask.GetDirection()).reshape(3, 3)
    if not origem_zero:  # aplica orientação e origem do DICOM (coordenadas do paciente, LPS)
        verts = verts @ D.T + np.array(mask.GetOrigin())
    malha = trimesh.Trimesh(verts, faces, process=True)  # skimage já gera normais para fora
    if np.linalg.det(D) < 0:
        malha.invert()
    return malha


def reduzir(malha: trimesh.Trimesh, fracao: float) -> trimesh.Trimesh:
    if fracao <= 0:
        return malha
    try:
        import fast_simplification
        # ponytail: a redução pode abrir a malha (não watertight); para impressão rode sem --reduzir ou repare no slicer
        v, f = fast_simplification.simplify(malha.vertices, malha.faces, target_reduction=fracao)
        return trimesh.Trimesh(v, f, process=True)
    except ImportError:
        print("[!] fast-simplification não instalado; pulando redução.")
        return malha


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="DICOM -> STL (somente osso)")
    ap.add_argument("pasta", type=Path, help="pasta com os arquivos DICOM")
    ap.add_argument("saida", type=Path, nargs="?", default=Path("osso.stl"))
    ap.add_argument("--limiar", type=float, help="limiar manual de osso")
    ap.add_argument("--limiar-max", type=float, default=1e9, help="exclui voxels acima (metal)")
    ap.add_argument("--info", action="store_true", help="só mostra estatísticas")
    ap.add_argument("--ilhas", type=int, default=1)
    ap.add_argument("--suavizar", type=int, default=10)
    ap.add_argument("--reduzir", type=float, default=0.0)
    ap.add_argument("--reamostrar", type=float, default=0.0)
    ap.add_argument("--origem-zero", action="store_true",
                    help="canto do volume em (0,0,0), sem origem/direção DICOM (Blue Sky Plan)")
    a = ap.parse_args()

    print(f"Lendo {a.pasta} ...")
    img = ler_serie(a.pasta)
    if a.info:
        info(img)
        return

    if a.reamostrar > 0:
        novo_sp = [a.reamostrar] * 3
        novo_tam = [int(round(s * sp / a.reamostrar)) for s, sp in zip(img.GetSize(), img.GetSpacing())]
        img = sitk.Resample(img, novo_tam, sitk.Transform(), sitk.sitkLinear,
                            img.GetOrigin(), novo_sp, img.GetDirection(), -1000.0)

    # filtro de mediana leve reduz ruído típico de CBCT
    img = sitk.Median(img, [1, 1, 1])

    limiar = a.limiar if a.limiar is not None else limiar_auto(sitk.GetArrayViewFromImage(img))
    print(f"Limiar de osso: {limiar:.1f} ({'manual' if a.limiar is not None else 'automático'})"
          + (f"  |  máximo: {a.limiar_max:.0f}" if a.limiar_max < 1e9 else ""))

    mask = segmentar(img, limiar, a.limiar_max, a.ilhas)
    malha = gerar_malha(mask, a.origem_zero)
    if a.suavizar > 0:
        trimesh.smoothing.filter_taubin(malha, iterations=a.suavizar)
    malha = reduzir(malha, a.reduzir)

    malha.export(a.saida)
    ext = malha.extents
    print(f"OK -> {a.saida}  |  {len(malha.faces):,} triângulos  |  "
          f"dimensões {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm  |  "
          f"fechada: {'sim' if malha.is_watertight else 'não'}")


if __name__ == "__main__":
    main()
