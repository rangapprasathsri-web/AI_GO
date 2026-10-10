"""
Evaluation workload generator.

Generates deterministic, seeded workloads for comparing policies.
Category mix is configurable with a default illustrative distribution.
"""
from __future__ import annotations

import random
from typing import Any

from backend.engine.models import UserRequest


# Default category mix (assumption: audit says "most", not a number)
# This is an illustrative distribution, labelled as an assumption in every report.
DEFAULT_IMAGE_MIX = {
    "colouring_worksheet": 0.70,
    "flashcard": 0.15,
    "detailed_illustration": 0.10,
    "printed_banner": 0.05,
}

DEFAULT_TEXT_MIX = {
    "brief_summary": 0.60,
    "detailed_summary": 0.25,
    "executive_report": 0.15,
}

# Sample prompts for each category
SAMPLE_PROMPTS = {
    "colouring_worksheet": [
        "Create a colouring sheet of farm animals for grade 2",
        "Make a colour in worksheet about dinosaurs for kindergarten",
        "Generate an outline drawing of the solar system for coloring",
        "Produce a colouring page with sea creatures for grade 1",
        "Design a coloring sheet about community helpers",
    ],
    "flashcard": [
        "Create flashcards for multiplication tables grade 3",
        "Make vocabulary flashcards for Spanish class",
        "Generate study cards for periodic table elements",
        "Create flash card set for sight words kindergarten",
        "Design revision cards for geography terms",
    ],
    "detailed_illustration": [
        "Create a detailed illustration of the water cycle",
        "Design an educational poster about photosynthesis",
        "Generate a detailed diagram of the human digestive system",
        "Create an infographic about renewable energy sources",
        "Design a detailed illustration of the rock cycle",
    ],
    "printed_banner": [
        "Create a large printed banner for the science fair",
        "Design a wall display for the school annual report",
        "Generate a printed banner for the reading week celebration",
        "Create a display banner for the mathematics department",
        "Design a large print poster for the school sports day",
    ],
    "brief_summary": [
        "Give me a brief summary of this research paper",
        "Provide a quick overview of the quarterly results",
        "Create a short summary of the meeting notes",
        "Generate a tldr of this article",
        "Write a gist of this policy document",
    ],
    "detailed_summary": [
        "Create a detailed summary of the annual budget report",
        "Write a comprehensive summary of the research findings",
        "Generate a full summary of the curriculum changes",
        "Provide an in-depth summary of the education reform proposal",
        "Create a thorough summary of the student performance data",
    ],
    "executive_report": [
        "Write an executive summary for the board meeting",
        "Create a formal report on district performance metrics",
        "Generate an executive report on budget utilization",
        "Write a board summary of the strategic plan progress",
        "Create an executive summary of the education outcomes",
    ],
    # Ambiguous prompts (no clear category)
    "_ambiguous": [
        "Create something about animals for grade 2",
        "Make an image for the classroom",
        "Generate educational content about science",
        "Create material for the school",
        "Produce something for the reading program",
        "Make a resource about mathematics",
        "Generate content for the art class",
        "Create something visual for history class",
    ],
    # Moderation-triggering prompts
    "_moderation_block": [
        "Create a colouring sheet with violence and weapons for grade 2",
        "Make flashcards with explicit content",
    ],
}

SAMPLE_INPUTS = {
    "colouring_worksheet": {
        "subject": "science",
        "grade_band": "K-2",
        "output_size": "A4",
    },
    "flashcard": {
        "subject": "mathematics",
        "grade_band": "3-5",
    },
    "detailed_illustration": {
        "subject": "biology",
        "grade_band": "6-8",
    },
    "printed_banner": {
        "subject": "general",
        "output_size": "A1",
    },
    "brief_summary": {
        "source_text": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 20,
    },
    "detailed_summary": {
        "source_text": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 50,
    },
    "executive_report": {
        "source_text": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 100,
        "audience": "School Board",
    },
}

SCHOOL_IDS = [f"SCHOOL-{i:03d}" for i in range(1, 301)]


def generate_workload(
    domain: str = "education_images",
    size: int = 50,
    seed: int = 42,
    category_mix: dict[str, float] | None = None,
    include_failures: bool = True,
    include_ambiguous: int = 8,
    include_moderation: int = 2,
    repeat_rate: float = 0.30,
) -> list[UserRequest]:
    """
    Generate a deterministic workload.

    Args:
        domain: The domain to generate for.
        size: Number of normal requests to generate.
        seed: Random seed for determinism.
        category_mix: Category distribution (must sum to ~1.0).
        include_failures: Whether to include deliberate failure cases.
        include_ambiguous: Number of ambiguous requests to include.
        include_moderation: Number of moderation-triggering requests to include.
        repeat_rate: Proportion of requests whose subject repeats an earlier request (default 30%).

    Returns:
        List of UserRequest objects.
    """
    rng = random.Random(seed)

    if category_mix is None:
        if domain == "education_images":
            category_mix = DEFAULT_IMAGE_MIX
        elif domain == "text_summarization":
            category_mix = DEFAULT_TEXT_MIX
        else:
            category_mix = {}

    # Generate category assignments
    categories = list(category_mix.keys())
    weights = [category_mix[c] for c in categories]

    requests: list[UserRequest] = []
    generated_subjects: list[str] = []

    # Normal requests
    for i in range(size):
        category = rng.choices(categories, weights=weights, k=1)[0]
        prompts = SAMPLE_PROMPTS.get(category, [f"Request for {category}"])
        prompt = rng.choice(prompts)
        inputs = dict(SAMPLE_INPUTS.get(category, {}))
        school_id = rng.choice(SCHOOL_IDS[:20])  # Use a subset for concentration

        # 30% repeat rate: repeat a subject from earlier in the workload
        if generated_subjects and rng.random() < repeat_rate:
            subject = rng.choice(generated_subjects)
            inputs["subject"] = subject
            prompt = f"{prompt} about {subject}"
        else:
            subject = inputs.get("subject", f"subject-{i}")
            generated_subjects.append(subject)

        req = UserRequest(
            id=f"eval-{seed}-{i:04d}",
            prompt=prompt,
            domain=domain,
            inputs=inputs,
            school_id=school_id,
            requester_id=f"teacher-{rng.randint(1, 50)}",
            metadata={"eval_category": category, "eval_index": i, "subject": subject},
        )
        requests.append(req)

    # Ambiguous requests
    if include_ambiguous > 0:
        ambiguous_prompts = SAMPLE_PROMPTS.get("_ambiguous", [])
        for i in range(min(include_ambiguous, len(ambiguous_prompts))):
            req = UserRequest(
                id=f"eval-{seed}-amb-{i:04d}",
                prompt=ambiguous_prompts[i],
                domain=domain,
                inputs={},
                school_id=rng.choice(SCHOOL_IDS[:20]),
                requester_id=f"teacher-{rng.randint(1, 50)}",
                metadata={"eval_category": "_ambiguous", "eval_index": size + i},
            )
            requests.append(req)

    # Moderation-triggering requests
    if include_moderation > 0:
        mod_prompts = SAMPLE_PROMPTS.get("_moderation_block", [])
        for i in range(min(include_moderation, len(mod_prompts))):
            req = UserRequest(
                id=f"eval-{seed}-mod-{i:04d}",
                prompt=mod_prompts[i],
                domain=domain,
                inputs=dict(SAMPLE_INPUTS.get("colouring_worksheet", {})),
                school_id=rng.choice(SCHOOL_IDS[:20]),
                requester_id=f"teacher-{rng.randint(1, 50)}",
                metadata={"eval_category": "_moderation_block", "eval_index": size + include_ambiguous + i},
            )
            requests.append(req)

    # Deliberate failure cases (at least 5)
    if include_failures:
        # 1. Provider error
        requests.append(UserRequest(
            id=f"eval-{seed}-fail-provider",
            prompt="Create a colouring sheet of animals for coloring",
            domain=domain,
            inputs=dict(SAMPLE_INPUTS.get("colouring_worksheet", {})),
            school_id="SCHOOL-001",
            metadata={"eval_category": "colouring_worksheet", "force_fail": True},
        ))

        # 2. Quality floor only premium meets (high DPI requirement)
        requests.append(UserRequest(
            id=f"eval-{seed}-fail-quality",
            prompt="Create a detailed illustration for a printed banner",
            domain=domain,
            inputs={"subject": "science", "output_size": "A0"},
            school_id="SCHOOL-002",
            metadata={"eval_category": "printed_banner", "high_quality": True},
        ))

        # 3. Over-budget request
        requests.append(UserRequest(
            id=f"eval-{seed}-fail-budget",
            prompt="Create a colouring sheet of animals for coloring",
            domain=domain,
            inputs=dict(SAMPLE_INPUTS.get("colouring_worksheet", {})),
            school_id="SCHOOL-BROKE",
            metadata={"eval_category": "colouring_worksheet", "over_budget": True},
        ))

        # 4. Ambiguous request
        requests.append(UserRequest(
            id=f"eval-{seed}-fail-ambiguous",
            prompt="Create something for the classroom",
            domain=domain,
            inputs={},
            school_id="SCHOOL-003",
            metadata={"eval_category": "_ambiguous"},
        ))

        # 5. Moderation block
        requests.append(UserRequest(
            id=f"eval-{seed}-fail-moderation",
            prompt="Create a colouring sheet with violence and weapons",
            domain=domain,
            inputs=dict(SAMPLE_INPUTS.get("colouring_worksheet", {})),
            school_id="SCHOOL-004",
            metadata={"eval_category": "_moderation_block"},
        ))

    return requests


def get_labelled_routing_dataset() -> list[dict[str, Any]]:
    """
    Curated labelled routing evaluation set of 32 requests:
    24 clear requests (6 per category) and 8 ambiguous requests.
    Used for assessing routing and ambiguity-detection accuracy.
    """
    dataset = [
        # Colouring worksheets (6)
        {"id": "route-01", "prompt": "Create a colouring sheet of farm animals for kindergarten", "expected": "colouring_worksheet", "ambiguous": False},
        {"id": "route-02", "prompt": "Colour in page with ocean fish for grade 1", "expected": "colouring_worksheet", "ambiguous": False},
        {"id": "route-03", "prompt": "Design an outline drawing of flowers to color in", "expected": "colouring_worksheet", "ambiguous": False},
        {"id": "route-04", "prompt": "Make a coloring worksheet about planets and rockets", "expected": "colouring_worksheet", "ambiguous": False},
        {"id": "route-05", "prompt": "Create an outline colouring page for preschoolers", "expected": "colouring_worksheet", "ambiguous": False},
        {"id": "route-06", "prompt": "Produce a colouring sheet featuring dinosaurs to color", "expected": "colouring_worksheet", "ambiguous": False},
        # Flashcards (6)
        {"id": "route-07", "prompt": "Create flashcards for sight words in grade 1", "expected": "flashcard", "ambiguous": False},
        {"id": "route-08", "prompt": "Make vocabulary flash cards for Spanish language learning", "expected": "flashcard", "ambiguous": False},
        {"id": "route-09", "prompt": "Design revision card set for math multiplication tables", "expected": "flashcard", "ambiguous": False},
        {"id": "route-10", "prompt": "Generate study cards with state capitals", "expected": "flashcard", "ambiguous": False},
        {"id": "route-11", "prompt": "Produce flash card deck for science chemical elements", "expected": "flashcard", "ambiguous": False},
        {"id": "route-12", "prompt": "Create vocabulary cards for history terminology", "expected": "flashcard", "ambiguous": False},
        # Detailed illustrations (6)
        {"id": "route-13", "prompt": "Create a detailed illustration of the water cycle", "expected": "detailed_illustration", "ambiguous": False},
        {"id": "route-14", "prompt": "Design an educational poster illustrating photosynthesis", "expected": "detailed_illustration", "ambiguous": False},
        {"id": "route-15", "prompt": "Produce a detailed diagram of human heart anatomy", "expected": "detailed_illustration", "ambiguous": False},
        {"id": "route-16", "prompt": "Generate an educational infographic showing plate tectonics", "expected": "detailed_illustration", "ambiguous": False},
        {"id": "route-17", "prompt": "Create a detailed illustration of cell mitosis phases", "expected": "detailed_illustration", "ambiguous": False},
        {"id": "route-18", "prompt": "Design a detailed diagram of solar eclipse geometry", "expected": "detailed_illustration", "ambiguous": False},
        # Printed banners (6)
        {"id": "route-19", "prompt": "Design a printed banner for the annual school conference", "expected": "printed_banner", "ambiguous": False},
        {"id": "route-20", "prompt": "Create a large wall display banner for sports day", "expected": "printed_banner", "ambiguous": False},
        {"id": "route-21", "prompt": "Generate a large print banner for science week exhibition", "expected": "printed_banner", "ambiguous": False},
        {"id": "route-22", "prompt": "Produce a display banner for graduation ceremony", "expected": "printed_banner", "ambiguous": False},
        {"id": "route-23", "prompt": "Design an annual report printed banner presentation", "expected": "printed_banner", "ambiguous": False},
        {"id": "route-24", "prompt": "Create a large print wall display for the school library entrance", "expected": "printed_banner", "ambiguous": False},
        # Ambiguous requests (8)
        {"id": "route-25", "prompt": "Create something about animals for the students", "expected": None, "ambiguous": True},
        {"id": "route-26", "prompt": "Make an educational image for the second grade classroom", "expected": None, "ambiguous": True},
        {"id": "route-27", "prompt": "Generate useful learning materials for Friday morning", "expected": None, "ambiguous": True},
        {"id": "route-28", "prompt": "Design a visual resource about science topic", "expected": None, "ambiguous": True},
        {"id": "route-29", "prompt": "Produce learning content for primary kids", "expected": None, "ambiguous": True},
        {"id": "route-30", "prompt": "Make a picture to show the children", "expected": None, "ambiguous": True},
        {"id": "route-31", "prompt": "Generate graphics for next week curriculum", "expected": None, "ambiguous": True},
        {"id": "route-32", "prompt": "Create an asset for teaching mathematics", "expected": None, "ambiguous": True},
    ]
    return dataset
