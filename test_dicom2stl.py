"""Checagem mínima: esfera sintética -> malha fechada, normais para fora, volume certo, em ambas as orientações."""
import numpy as np
import SimpleITK as sitk

from dicom2stl_osso import gerar_malha


def test_esfera():
    z, y, x = np.mgrid[:48, :48, :48]
    arr = ((x - 24) ** 2 + (y - 24) ** 2 + (z - 24) ** 2 < 15 ** 2).astype(np.uint8)
    esperado = 4 / 3 * np.pi * (15 * 0.5) ** 3
    for D in (np.eye(3), np.diag([1.0, 1.0, -1.0])):
        img = sitk.GetImageFromArray(arr)
        img.SetSpacing((0.5, 0.5, 0.5))
        img.SetDirection(D.flatten())
        m = gerar_malha(img)
        assert m.is_watertight, f"malha aberta (det {np.linalg.det(D):+.0f})"
        assert m.volume > 0, f"normais para dentro: volume {m.volume:.1f} (det {np.linalg.det(D):+.0f})"
        assert abs(m.volume - esperado) / esperado < 0.03, f"volume {m.volume:.1f} vs {esperado:.1f}"
    # --origem-zero ignora origem e direção: canto do volume em (0,0,0)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((0.5, 0.5, 0.5))
    img.SetOrigin((10.0, 20.0, -130.0))
    assert np.allclose(gerar_malha(img).bounds[0], (10 + 4.5, 20 + 4.5, -130 + 4.5), atol=0.6)
    assert np.allclose(gerar_malha(img, origem_zero=True).bounds[0], (4.5, 4.5, 4.5), atol=0.6)


if __name__ == "__main__":
    test_esfera()
    print("ok")
