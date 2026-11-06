import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'automation/scene-effects-lab/score.py'
spec = importlib.util.spec_from_file_location('scene_judge', path)
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def result(**overrides):
    return dict(
        scores=dict.fromkeys(judge.WEIGHTS, 100) | overrides,
        critical_issues=[],
        evidence='Visible evidence',
        improvements=[],
    )


def test_fixed_weights_and_pass_threshold():
    assert sum(judge.WEIGHTS.values()) == pytest.approx(1)
    assert judge.grade(result())['passed'] is True
    assert judge.grade(result(spectacle=40))['score'] == 76
    assert judge.grade(result(originality=0))['score'] == 95
    assert judge.grade(result(originality=0))['passed'] is True


def test_critical_defect_cannot_pass():
    value = result()
    value['critical_issues'] = ['Held sung word clipped']
    assert judge.grade(value)['score'] == 94
    assert judge.grade(value)['passed'] is False


def test_rounding_cannot_turn_a_failure_into_a_pass():
    value=result(**dict.fromkeys(judge.WEIGHTS,94.999))
    assert judge.grade(value)['passed'] is False


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, -1, 101, '95', None])
def test_invalid_scores_are_not_accepted(value):
    with pytest.raises(ValueError):
        judge.grade(result(spectacle=value))
