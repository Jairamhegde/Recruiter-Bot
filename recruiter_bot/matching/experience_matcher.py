def experience_fit(experience_years: int, min_experience_years: int) -> float:
    """1.0 at or above the minimum; proportional below it. Extra years are not penalized."""
    if min_experience_years == 0:
        return 1.0
    if experience_years >= min_experience_years:
        return 1.0
    return experience_years / min_experience_years
