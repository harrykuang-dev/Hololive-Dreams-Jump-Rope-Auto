"""Reject accidental research imports or game resources in product bundles."""
import pytest

from tools.verify_release_bundle import verify_research_boundary


def test_normal_runtime_and_existing_ui_assets_are_allowed():
    verify_research_boundary(
        ['rope_track', 'vision', 'numpy', 'cv2', 'tkinter'],
        ['assets\\startup\\next.png', 'assets\\startup\\ok.png',
         'assets\\startup\\play.png', 'assets\\jump-rope.ico', 'LICENSE'],
    )


@pytest.mark.parametrize('modules,files', [
    (['UnityPy.files'], []),
    (['octodb_pb2'], []),
    ([], ['work\\hololive-toolkit-research\\curve.json']),
    ([], ['assets\\rope-mask.png']),
    ([], ['data\\rope.unity3d']),
    ([], ['data\\GameAssembly.dll']),
    ([], ['data\\global-metadata.dat']),
])
def test_accidental_research_payload_is_rejected(modules, files):
    with pytest.raises(ValueError):
        verify_research_boundary(modules, files)
