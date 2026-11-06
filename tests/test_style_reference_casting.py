"""An old style preset must not cast its pictured person as the story's lead."""
from direction.entities import sheet_style, sheet_prompt, reference_role
from direction.illustration_prompts import image_prompt
from direction.prompt_fit import fit_prompts


LEGACY = 'Always use the likeness of the reference image for the main character.'
STYLE = 'Soft painterly shading. ' + LEGACY


def test_style_instruction_cannot_override_viktoria_sheet():
    lead = dict(name='Dr. Viktoria', kind='character', looks='Dark hair pulled back, white lab coat.')
    prompt = sheet_prompt(lead, sheet_style(dict(style_prompt=STYLE)))
    assert LEGACY not in prompt
    assert 'Soft painterly shading' in prompt
    assert 'Dr. Viktoria' in prompt
    scene = reference_role('Dr. Viktoria examines a water bug.', [lead], 0, 1, False)
    assert 'Do not draw its people or objects' in scene
    assert 'Reference image 2 shows Dr. Viktoria' in scene


def test_style_cleanup_preserves_explicit_likeness_role():
    layout = dict(artwork_mode='fullscreen', visual_prompt='Full frame.')
    for likeness in (False, True):
        prompt = image_prompt('A woman in a laboratory', layout, STYLE, True, likeness)
        assert LEGACY not in prompt
        assert ('The reference image shows the main character' in prompt) == likeness


def test_prompt_fitting_does_not_reintroduce_casting():
    def no_rewrite(*args, **kwargs):
        raise AssertionError('Short prompts do not need an AI rewrite')

    prompts = fit_prompts(no_rewrite, 'unused', 'Qwen/Qwen-Image-2.1', ['Viktoria examines a bug.'], STYLE)
    assert LEGACY not in prompts[0]
    assert 'Soft painterly shading' in prompts[0]
