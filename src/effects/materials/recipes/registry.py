"""The recipe registry: every material entrance and exit, by effect id."""

RECIPES = {}


def recipe(effect_id, phase, pad=0.6, work_height=None):
    """Register a painter; the effect's name and description live in its JSON recipe and descriptions.json."""

    def register(function):
        RECIPES[effect_id] = dict(phase=phase, pad=pad, paint=function, work_height=work_height)
        return function

    return register
