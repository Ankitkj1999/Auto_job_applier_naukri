import os
import glob
import logging
from typing import Optional

logger = logging.getLogger("NaukriBot")


def resolve_resume_path(config: dict, base_dir: Optional[str] = None) -> Optional[str]:
    """
    Resolves the resume PDF path following a portable precedence order:
    1. Check config["personals"]["default_resume_path"] if non-empty and file exists.
    2. Check base_dir for any direct *.pdf files (e.g. user dropped resume in project root).
    3. Check base_dir/resumes or base_dir/resume for any *.pdf files.
    4. Return None if no valid PDF is found.

    Args:
        config: Dict representing loaded config.json.
        base_dir: Optional directory path to search. Defaults to project directory.

    Returns:
        Absolute path to an existing PDF file, or None.
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    personals = config.get("personals", {}) if isinstance(config, dict) else {}
    configured_path = personals.get("default_resume_path", "")

    # 1. Configured path exists?
    if configured_path:
        expanded = os.path.abspath(os.path.expanduser(str(configured_path).strip()))
        if os.path.isfile(expanded):
            return expanded
        else:
            logger.info(f"Configured resume path '{configured_path}' not found on disk. Auto-detecting in project folder...")

    # 2. Search root directory for *.pdf
    root_pdfs = sorted(glob.glob(os.path.join(base_dir, "*.pdf")))
    if root_pdfs:
        selected = os.path.abspath(root_pdfs[0])
        logger.info(f"✓ Auto-detected resume in project root: {os.path.basename(selected)} ({selected})")
        return selected

    # 3. Search subdirectories (resumes/, resume/, docs/)
    for sub in ["resumes", "resume", "docs"]:
        sub_dir = os.path.join(base_dir, sub)
        if os.path.isdir(sub_dir):
            sub_pdfs = sorted(glob.glob(os.path.join(sub_dir, "*.pdf")))
            if sub_pdfs:
                selected = os.path.abspath(sub_pdfs[0])
                logger.info(f"✓ Auto-detected resume in '{sub}/': {os.path.basename(selected)} ({selected})")
                return selected

    logger.warning("No resume PDF found in config or project folder. Please provide a .pdf file.")
    return None
