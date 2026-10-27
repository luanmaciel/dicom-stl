#!/usr/bin/env python3
"""
anonimizar.py - Copia os .dcm de uma pasta para outra sem dados do paciente.

Uso:
    python anonimizar.py PASTA_ORIGEM PASTA_DESTINO [--id paciente01] [--manter-datas]

Os originais não são tocados. A saída é renomeada para ID_0001.dcm, ID_0002.dcm...
porque o nome de arquivo exportado pelo i-CAT contém o nome do paciente.
Pixels, posição/orientação, espaçamento, rescale e fabricante ficam como estão.
"""
import argparse
import sys
from pathlib import Path

import pydicom
from pydicom.uid import generate_uid

# branqueadas sempre; o grupo (0010,xxxx) inteiro (nome, ID, nascimento, sexo, endereço,
# telefone, outros IDs...) é apagado à parte
IDENTIDADE = [
    "InstitutionName", "InstitutionAddress", "ReferringPhysicianName",
    "PerformingPhysicianName", "OperatorsName", "StationName",
    "AccessionNumber", "StudyID", "StudyComments", "DeviceSerialNumber",
]
DATAS = [
    "StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate", "InstanceCreationDate",
    "StudyTime", "SeriesTime", "AcquisitionTime", "ContentTime", "InstanceCreationTime",
]
UIDS = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID"]


def anonimizar(arquivos, destino: Path, id="ANON", manter_datas=False):
    """Anonimiza cada arquivo em `arquivos` e grava em `destino`. Devolve os caminhos gravados."""
    destino.mkdir(parents=True, exist_ok=True)
    novos_uids = {}  # velho -> novo, consistente em toda a série (SimpleITK agrupa por SeriesInstanceUID)
    saidas = []
    for i, f in enumerate(sorted(arquivos), 1):
        ds = pydicom.dcmread(f)
        for e in list(ds):
            if e.tag.group == 0x0010:
                del ds[e.tag]
        ds.PatientName = ds.PatientID = id
        ds.PatientBirthDate = ds.PatientSex = ""
        for kw in IDENTIDADE + ([] if manter_datas else DATAS):
            if kw in ds:
                ds[kw].value = ""
        for kw in UIDS:
            if kw in ds:
                ds[kw].value = novos_uids.setdefault(ds[kw].value, generate_uid())
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.remove_private_tags()
        out = destino / f"{id}_{i:04d}.dcm"
        ds.save_as(out)
        saidas.append(out)
    return saidas


def main():
    ap = argparse.ArgumentParser(description="Copia .dcm anonimizados para outra pasta")
    ap.add_argument("origem", type=Path, help="pasta com os .dcm originais (não é alterada)")
    ap.add_argument("destino", type=Path, help="pasta nova para a cópia anonimizada")
    ap.add_argument("--id", default="ANON", help="texto gravado em PatientName/PatientID")
    ap.add_argument("--manter-datas", action="store_true", help="não apaga datas/horas do exame")
    a = ap.parse_args()
    if a.destino.resolve() == a.origem.resolve():
        sys.exit("Destino não pode ser a pasta de origem.")
    arquivos = list(a.origem.glob("*.dcm"))
    if not arquivos:
        sys.exit(f"Nenhum .dcm em {a.origem}")
    saidas = anonimizar(arquivos, a.destino, a.id, a.manter_datas)
    print(f"OK -> {a.destino}  |  {len(saidas)} arquivos  |  PatientName/ID = {a.id}")


if __name__ == "__main__":
    main()
