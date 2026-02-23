import re
from typing import Dict, Any, List, Optional, Tuple


def normalize_text(text: str) -> str:
    """Normalize text for comparison (remove extra whitespace, newlines, etc.)"""
    # Replace multiple whitespace/newlines with single space
    text = re.sub(r"\s+", " ", text)
    # Remove special characters that might differ
    text = text.strip()
    return text


def find_text_in_paragraphs(
    search_text: str, paragraphs: List[Dict[str, Any]], threshold: float = 0.6
) -> List[Dict[str, Any]]:
    """
    Find matching paragraphs for the search text.

    Args:
        search_text: Text to search for
        paragraphs: List of paragraph dictionaries from raw_analysis.json
        threshold: Minimum similarity threshold (0-1)

    Returns:
        List of matching paragraphs with bounding box information
    """
    normalized_search = normalize_text(search_text)
    matches = []

    for para in paragraphs:
        para_content = para.get("content", "")
        normalized_para = normalize_text(para_content)

        # Check for substring match (search text in paragraph or paragraph in search)
        if normalized_search in normalized_para or normalized_para in normalized_search:
            # Calculate similarity using character overlap
            search_chars = set(normalized_search.lower())
            para_chars = set(normalized_para.lower())
            overlap = len(search_chars & para_chars)
            similarity = overlap / max(len(search_chars), len(para_chars), 1)

            if similarity >= threshold:
                match_info = {
                    "paragraph_content": para_content,
                    "similarity": similarity,
                    "bounding_regions": para.get("boundingRegions", []),
                    "role": para.get("role"),
                    "spans": para.get("spans", []),
                }
                matches.append(match_info)
        # Also check for partial matches (if search text is long, check if significant portion matches)
        elif len(normalized_search) > 20:
            # Try to find if a significant portion of the search text appears in the paragraph
            search_words = set(normalized_search.lower().split())
            para_words = set(normalized_para.lower().split())
            if len(search_words) > 0:
                word_overlap = len(search_words & para_words)
                word_similarity = word_overlap / len(search_words)
                if word_similarity >= 0.5:  # At least 50% of words match
                    match_info = {
                        "paragraph_content": para_content,
                        "similarity": word_similarity,
                        "bounding_regions": para.get("boundingRegions", []),
                        "role": para.get("role"),
                        "spans": para.get("spans", []),
                    }
                    matches.append(match_info)

    return matches


def find_text_in_lines(
    search_text: str, pages: List[Dict[str, Any]], threshold: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find matching lines for the search text.

    Args:
        search_text: Text to search for
        pages: List of page dictionaries from raw_analysis.json
        threshold: Minimum similarity threshold

    Returns:
        List of matching lines with bounding box information
    """
    normalized_search = normalize_text(search_text)
    matches = []

    for page in pages:
        page_number = page.get("pageNumber", 0)
        lines = page.get("lines", [])

        for line in lines:
            line_content = line.get("content", "")
            normalized_line = normalize_text(line_content)

            # Check for substring match
            if (
                normalized_search in normalized_line
                or normalized_line in normalized_search
            ):
                search_chars = set(normalized_search.lower())
                line_chars = set(normalized_line.lower())
                overlap = len(search_chars & line_chars)
                similarity = overlap / max(len(search_chars), len(line_chars), 1)

                if similarity >= threshold:
                    match_info = {
                        "line_content": line_content,
                        "page_number": page_number,
                        "similarity": similarity,
                        "polygon": line.get("polygon", []),
                        "spans": line.get("spans", []),
                    }
                    matches.append(match_info)
            # Also check word-level matching for longer texts
            elif len(normalized_search) > 15:
                search_words = set(normalized_search.lower().split())
                line_words = set(normalized_line.lower().split())
                if len(search_words) > 0:
                    word_overlap = len(search_words & line_words)
                    word_similarity = word_overlap / len(search_words)
                    if word_similarity >= 0.4:
                        match_info = {
                            "line_content": line_content,
                            "page_number": page_number,
                            "similarity": word_similarity,
                            "polygon": line.get("polygon", []),
                            "spans": line.get("spans", []),
                        }
                        matches.append(match_info)

    return matches


def match_reference_to_bounding_box(
    reference_text: str,
    raw_analysis: Dict[str, Any],
    para_threshold: float = 0.6,
    line_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Match a single reference text to bounding boxes in the raw analysis.

    Args:
        reference_text: The text excerpt to match
        raw_analysis: The complete raw analysis dictionary from Azure Document Intelligence
        para_threshold: Minimum similarity threshold for paragraph matching
        line_threshold: Minimum similarity threshold for line matching

    Returns:
        Dictionary with matching information including bounding boxes
    """
    paragraphs = raw_analysis.get("paragraphs", [])
    pages = raw_analysis.get("pages", [])

    # Try to find in paragraphs first (more accurate)
    para_matches = find_text_in_paragraphs(reference_text, paragraphs, para_threshold)

    # Also try to find in lines (for more granular matching)
    line_matches = find_text_in_lines(reference_text, pages, line_threshold)

    result = {
        "text": reference_text,
        "paragraph_matches": para_matches,
        "line_matches": line_matches,
        "best_match": None,
    }

    # Determine best match (prefer paragraph matches with highest similarity)
    if para_matches:
        best_para = max(para_matches, key=lambda x: x["similarity"])
        bounding_regions = best_para["bounding_regions"]
        # Format bounding box info
        bbox_info = []
        page_number = None
        for region in bounding_regions:
            page_num = region.get("pageNumber", region.get("page_number"))
            if page_num and not page_number:
                page_number = page_num
            bbox_info.append(
                {"page_number": page_num, "polygon": region.get("polygon", [])}
            )

        result["best_match"] = {
            "type": "paragraph",
            "content": best_para["paragraph_content"],
            "similarity": best_para["similarity"],
            "page_number": page_number,  # Add page_number at top level for easy access
            "bounding_regions": bbox_info,
            "role": best_para.get("role"),
        }
    elif line_matches:
        best_line = max(line_matches, key=lambda x: x["similarity"])
        result["best_match"] = {
            "type": "line",
            "content": best_line["line_content"],
            "similarity": best_line["similarity"],
            "page_number": best_line["page_number"],
            "polygon": best_line["polygon"],
        }

    return result


def match_references_to_bounding_boxes(
    references: List[Dict[str, Any]],
    raw_analysis: Dict[str, Any],
    para_threshold: float = 0.6,
    line_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    Match multiple reference texts to bounding boxes in the raw analysis.

    Args:
        references: List of reference dictionaries, each with at least a 'text' field
        raw_analysis: The complete raw analysis dictionary from Azure Document Intelligence
        para_threshold: Minimum similarity threshold for paragraph matching
        line_threshold: Minimum similarity threshold for line matching

    Returns:
        List of dictionaries with matching information for each reference
    """
    results = []

    for ref_idx, ref in enumerate(references):
        ref_text = ref.get("text", "")
        if not ref_text:
            continue

        match_result = match_reference_to_bounding_box(
            ref_text, raw_analysis, para_threshold, line_threshold
        )

        # Add reference index and preserve any additional fields from the original reference
        match_result["reference_index"] = ref_idx
        if "context" in ref:
            match_result["context"] = ref["context"]

        results.append(match_result)

    return results


def extract_figure_references(text: str) -> List[Tuple[str, str]]:
    """
    Extract figure references from text using regex patterns.

    Args:
        text: Text to search for figure references

    Returns:
        List of tuples (figure_reference, figure_id) like [("Figure 1.1", "1.1"), ("Fig. 2.3", "2.3")]
    """
    # Patterns to match figure references
    patterns = [
        r"\bFigure\s+(\d+(?:\.\d+)*)",  # "Figure 1.1", "Figure 2"
        r"\bFig\.?\s+(\d+(?:\.\d+)*)",  # "Fig 1.1", "Fig. 2.3"
        r"\bFIGURE\s+(\d+(?:\.\d+)*)",  # "FIGURE 1.1"
        r"\bFIG\.?\s+(\d+(?:\.\d+)*)",  # "FIG 1.1"
    ]

    figure_refs = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Create the full reference text and the figure ID
            if "Figure" in pattern.upper():
                full_ref = f"Figure {match}"
            elif "Fig." in pattern:
                full_ref = f"Fig. {match}"
            elif "FIG." in pattern:
                full_ref = f"FIG. {match}"
            else:
                full_ref = f"Fig {match}"
            figure_refs.append((full_ref, match))

    return figure_refs


def find_figure_by_id(
    figure_id: str, figures: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Find a figure by its ID in the figures list.
    Includes fallback logic for mismatched figure numbering between document text and Azure Doc Intelligence.

    Args:
        figure_id: Figure ID to search for (e.g., "1.1", "2.3", or just "1", "2")
        figures: List of figure dictionaries

    Returns:
        Figure dictionary if found, None otherwise
    """
    # First try exact match
    for figure in figures:
        if figure.get("id") == figure_id:
            return figure

    # If no exact match, try fallback strategies
    # Strategy 1: If figure_id is just a number (like "1"), try to find figures that start with that number
    if figure_id.isdigit():
        target_num = int(figure_id)
        for figure in figures:
            fig_id = figure.get("id", "")
            # Try patterns like "1.1", "1.2", "2.1", etc.
            if fig_id.startswith(f"{target_num}.") or fig_id == str(target_num):
                print(f"[FIGURE_MATCHING] Fallback match: '{figure_id}' -> '{fig_id}'")
                return figure

    # Strategy 2: Sequential mapping - Azure often assigns IDs like "1.1", "2.1", "3.1" sequentially
    # If document says "Fig. 1" and "Fig. 2", map them to the first N figures in order
    if figure_id.isdigit():
        target_num = int(figure_id)
        # Sort figures by their ID to get sequential order
        sorted_figures = sorted(figures, key=lambda f: f.get("id", ""))

        # If we have fewer figures than the target number, try direct indexing
        if target_num <= len(sorted_figures):
            selected_figure = sorted_figures[target_num - 1]  # 1-indexed to 0-indexed
            print(
                f"[FIGURE_MATCHING] Sequential mapping: '{figure_id}' -> figure at index {target_num - 1} (ID: {selected_figure.get('id')})"
            )
            return selected_figure

    # Strategy 3: Try to match by page proximity and caption similarity
    # For documents where figure numbering doesn't match, try to find figures on the same page
    # This is a more advanced strategy that could be implemented later

    print(
        f"[FIGURE_MATCHING] No figure found for ID: '{figure_id}' (checked {len(figures)} figures)"
    )
    return None


def match_figure_references_to_bounding_boxes(
    references: List[Dict[str, Any]],
    raw_analysis: Dict[str, Any],
    figures: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Match figure references to figure bounding boxes in addition to text references.
    Enhanced to ensure all references get bounding boxes.

    Args:
        references: List of reference dictionaries from LLM responses
        raw_analysis: Raw analysis from Azure Document Intelligence
        figures: List of figure metadata dictionaries

    Returns:
        Updated references list with both text and figure bounding box matches
    """
    print(
        f"[FIGURE_MATCHING] Starting enhanced figure reference matching with {len(figures)} figures"
    )
    figure_ids = [f.get("id", "unknown") for f in figures]
    print(f"[FIGURE_MATCHING] Available figure IDs: {figure_ids}")

    # First, run text matching on ALL references to ensure they all get bounding boxes
    text_matched_refs = match_references_to_bounding_boxes(references, raw_analysis)
    print(
        f"[FIGURE_MATCHING] Text matching completed for {len(text_matched_refs)} references"
    )

    # Now enhance references that contain figure references with figure information
    enhanced_references = []

    for ref in text_matched_refs:
        ref_text = ref.get("text", "")
        figure_refs = extract_figure_references(ref_text)

        print(f"[FIGURE_MATCHING] Processing reference: '{ref_text[:100]}...'")
        print(f"[FIGURE_MATCHING] Extracted figure refs: {figure_refs}")

        if figure_refs:
            # This reference contains figure references
            # Enhance the existing text-matched reference with figure information
            enhanced_ref = dict(ref)  # Copy the text-matched reference

            # Add figure information to the best_match
            if ref.get("best_match"):
                enhanced_best_match = dict(ref["best_match"])
                # Add figure metadata to the existing best_match
                for full_ref, figure_id in figure_refs:
                    print(f"[FIGURE_MATCHING] Looking for figure ID: '{figure_id}'")
                    figure = find_figure_by_id(figure_id, figures)
                    if figure:
                        print(
                            f"[FIGURE_MATCHING] ✅ Found matching figure: {figure.get('id')} on page {figure.get('page')}"
                        )
                        # Add figure information to the best_match
                        enhanced_best_match["figure_id"] = figure_id
                        enhanced_best_match["figure_reference"] = full_ref
                        enhanced_best_match["figure_caption"] = figure.get("caption")
                        # Keep the text bounding box but add figure type information
                        enhanced_best_match["has_figure_reference"] = True
                        break  # Only handle the first figure reference found

                enhanced_ref["best_match"] = enhanced_best_match
            else:
                # No text match found, but figure reference exists - create figure-only reference
                for full_ref, figure_id in figure_refs:
                    figure = find_figure_by_id(figure_id, figures)
                    if figure:
                        print(
                            f"[FIGURE_MATCHING] Creating figure-only reference for: '{figure_id}'"
                        )
                        enhanced_ref["best_match"] = {
                            "type": "figure",
                            "similarity": 1.0,
                            "page_number": figure.get("page"),
                            "bounding_regions": figure.get("bounding_regions", []),
                            "polygon": (
                                figure.get("bounding_regions", [{}])[0].get(
                                    "polygon", []
                                )
                                if figure.get("bounding_regions")
                                else []
                            ),
                            "caption": figure.get("caption"),
                            "figure_id": figure_id,
                            "figure_reference": full_ref,
                        }
                        break

            enhanced_references.append(enhanced_ref)
        else:
            # No figure references, keep the text-matched reference as-is
            enhanced_references.append(ref)

    print(
        f"[FIGURE_MATCHING] Enhanced {len(enhanced_references)} references with figure information"
    )
    return enhanced_references