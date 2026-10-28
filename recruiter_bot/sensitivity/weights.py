"""The three weights of the match score, and how to recompute a score with different ones (D-48).

The production formula (D-32) is:

    score = 100 x (skills_weight x skill_score
                   + experience_weight x experience_score
                   + culture_weight x culture_score)

When a job lists no culture keywords there is no culture score, and the two remaining
weights are rescaled so they still add up to 1.
"""
from dataclasses import dataclass

from recruiter_bot.matching.match_scorer import CULTURE_WEIGHT, EXPERIENCE_WEIGHT, SKILL_WEIGHT


@dataclass(frozen=True)
class Weights:
    skills: float
    experience: float
    culture: float

    def total(self) -> float:
        return self.skills + self.experience + self.culture

    def scaled_to_one(self) -> "Weights":
        """The same proportions, but adding up to exactly 1."""
        total = self.total()
        return Weights(self.skills / total, self.experience / total, self.culture / total)

    def describe(self) -> str:
        return f"skills {self.skills:.2f} / experience {self.experience:.2f} / culture {self.culture:.2f}"


# The weights the API uses today, read from the scorer so the two can never disagree.
PRODUCTION_WEIGHTS = Weights(skills=SKILL_WEIGHT, experience=EXPERIENCE_WEIGHT, culture=CULTURE_WEIGHT)


def recompute_score(
    skill_score: float,
    experience_score: float,
    culture_score: float | None,
    weights: Weights,
) -> float:
    """The match score these three parts would get with these weights. Mirrors match_scorer.score_match."""
    if culture_score is None:
        # The job has no culture keywords: leave culture out and rescale the other two weights.
        weighted = (weights.skills * skill_score + weights.experience * experience_score) / (
            weights.skills + weights.experience
        )
    else:
        weighted = (
            weights.skills * skill_score
            + weights.experience * experience_score
            + weights.culture * culture_score
        )
    return round(100 * weighted, 1)
