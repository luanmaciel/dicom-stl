"""Checagem mínima: 2 fatias anonimizadas -> tags somem, UIDs trocam de forma consistente, pixels intactos.

Não usa exame real: as fatias são geradas com pydicom numa pasta temporária, com dados fictícios.
"""
import tempfile
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ImplicitVRLittleEndian, generate_uid

from anonimizar import anonimizar


def fatias_sinteticas(pasta: Path, n=2):
    """Grava n fatias de TC fictícias (8x8) com identificação preenchida. Devolve os caminhos."""
    uids = {kw: generate_uid() for kw in ("StudyInstanceUID", "SeriesInstanceUID", "FrameOfReferenceUID")}
    saidas = []
    for i in range(n):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ImplicitVRLittleEndian
        out = pasta / f"Exemplo_Paciente_{i:03d}.dcm"  # nome de arquivo com "nome do paciente", como o scanner exporta
        ds = FileDataset(str(out), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        for kw, uid in uids.items():
            setattr(ds, kw, uid)
        ds.Modality = "CT"
        ds.PatientName = "Paciente^Exemplo"
        ds.PatientID = "000123"
        ds.PatientBirthDate = "19800101"
        ds.PatientSex = "M"
        ds.InstitutionName = "Clinica Exemplo"
        ds.StationName = "CBCT01"
        ds.OperatorsName = "Operador^Exemplo"
        ds.ReferringPhysicianName = "Dr^Exemplo"
        ds.StudyDate = ds.AcquisitionDate = "20240101"
        ds.AcquisitionTime = "120000"
        ds.ImagePositionPatient = [0.0, 0.0, 0.3 * i]
        ds.PixelSpacing = [0.3, 0.3]
        ds.RescaleIntercept = -1000
        ds.RescaleSlope = 1
        ds.Rows = ds.Columns = 8
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = np.full((8, 8), 100 + i, dtype=np.uint16).tobytes()
        ds.save_as(out)
        saidas.append(out)
    return saidas


def test_anonimizar():
    with tempfile.TemporaryDirectory() as origem, tempfile.TemporaryDirectory() as tmp:
        orig = fatias_sinteticas(Path(origem))
        oa, ob = [pydicom.dcmread(p) for p in orig]
        novos = anonimizar(orig, Path(tmp), id="paciente01")
        assert len(novos) == 2 and "Exemplo" not in novos[0].name
        a, b = [pydicom.dcmread(p) for p in novos]
        for ds in (a, b):
            assert ds.PatientName == "paciente01" and ds.PatientID == "paciente01"
            assert ds.PatientBirthDate == "" and ds.PatientSex == ""
            for kw in ("InstitutionName", "StationName", "OperatorsName", "ReferringPhysicianName",
                       "StudyDate", "AcquisitionDate", "AcquisitionTime"):
                assert ds[kw].value == "", kw
            assert "Exemplo" not in str(ds)
        for kw in ("StudyInstanceUID", "SeriesInstanceUID", "FrameOfReferenceUID"):
            assert a[kw].value == b[kw].value != oa[kw].value, kw
        assert a.SOPInstanceUID != b.SOPInstanceUID != oa.SOPInstanceUID
        assert a.SOPInstanceUID == a.file_meta.MediaStorageSOPInstanceUID
        assert a.PixelData == oa.PixelData and b.PixelData == ob.PixelData
        assert a.ImagePositionPatient == oa.ImagePositionPatient
        assert b.ImagePositionPatient == ob.ImagePositionPatient
        assert a.PixelSpacing == oa.PixelSpacing and a.RescaleIntercept == oa.RescaleIntercept
        c = pydicom.dcmread(anonimizar(orig[:1], Path(tmp) / "datas", manter_datas=True)[0])
        assert c.StudyDate == oa.StudyDate and c.PatientName == "ANON"
        assert pydicom.dcmread(orig[0]).PatientName == "Paciente^Exemplo"  # originais intactos


if __name__ == "__main__":
    test_anonimizar()
    print("ok")
