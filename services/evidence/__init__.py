"""
证据模块服务层
"""
from services.evidence.classifier import classify_text, classify_material, classify_by_filename, classify_with_filename_fallback
from services.evidence.catalog_generator import generate_catalog
from services.evidence.document_analyzer import analyze_catalog
from services.evidence.word_generator import generate_filing_evidence, generate_complaint, generate_appraisal_application
from services.evidence.excel_generator import generate_compensation_summary, generate_fee_type_detail, generate_all_fee_details
from services.evidence.pdf_generator import generate_catalog_pdf_inline
from services.evidence.bundle_packager import create_export_bundle

__all__ = [
    "classify_text",
    "classify_material",
    "classify_by_filename",
    "classify_with_filename_fallback",
    "generate_catalog",
    "analyze_catalog",
    "generate_filing_evidence",
    "generate_complaint",
    "generate_appraisal_application",
    "generate_compensation_summary",
    "generate_fee_type_detail",
    "generate_all_fee_details",
    "generate_catalog_pdf_inline",
    "create_export_bundle",
]
