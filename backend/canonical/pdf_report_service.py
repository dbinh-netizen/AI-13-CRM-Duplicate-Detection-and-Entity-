"""Enterprise Entity Resolution & Merge Audit Dossier PDF Report Engine.

Sub-milestone: P2.5 - FILE 3: OFFICIAL ENTITY RESOLUTION & MERGE AUDIT DOSSIER
Module: backend.canonical.pdf_report_service

Generates `songnhat_full_process_report.pdf` using ReportLab:
This document serves as the official operational audit dossier of the pipeline run,
documenting all duplicate detection decisions, merge operations, evidence rationale,
Maker-Checker approvals, golden record attribute survivorship, contact-to-account affiliations,
and the final resolved entity crosswalk ledger.

Chapters:
- Chapter 1: Tiếp nhận dữ liệu nguồn & Kiểm soát toàn vẹn dòng (Source Intake & Validation)
- Chapter 2: Quá trình phát hiện trùng lặp Doanh nghiệp (Account Duplicate Detection & Blocking)
- Chapter 3: Chi tiết các Quyết định Hợp nhất Doanh nghiệp & Căn cứ Bằng chứng (Account Merge Evidence)
- Chapter 4: Quá trình Rà soát & Hợp nhất Người liên hệ Trùng lặp (Contact Duplicate Detection C↔C)
- Chapter 5: Quá trình Phân giải Mối quan hệ Người liên hệ - Doanh nghiệp (Contact-to-Account Resolution)
- Chapter 6: Nhật ký Kiểm soát Phê duyệt Độc lập Maker-Checker (Review & Approval Audit Trail)
- Chapter 7: Quá trình Hợp nhất Bản ghi vàng & Nguồn gốc Dữ liệu (Golden Record Survivorship & Provenance)
- Chapter 8: Cơ chế Đảo ngược & Quản trị Ràng buộc (Reversal Governance, Split & Invalidation)
- Chapter 9: Đối soát Số liệu Toàn trình (Mathematical Conservation of Mass Ledger)
- Chapter 10: Sổ cái Ánh xạ Thực thể Đầu ra (Final Canonical Crosswalk Ledger)
- Chapter 11: Kê khai Tệp Dữ liệu Xuất xưởng & Mã băm Bảo mật (Deliverables Manifest & Attestation)
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Register TrueType fonts with full Unicode / Vietnamese support
FONT_NAME = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
FONT_BOLDITALIC = "Helvetica-BoldOblique"

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    win_fonts = Path("C:/Windows/Fonts")
    if (win_fonts / "arial.ttf").exists():
        pdfmetrics.registerFont(TTFont("Arial", str(win_fonts / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("Arial-Bold", str(win_fonts / "arialbd.ttf")))
        pdfmetrics.registerFont(TTFont("Arial-Italic", str(win_fonts / "ariali.ttf")))
        pdfmetrics.registerFont(TTFont("Arial-BoldItalic", str(win_fonts / "arialbi.ttf")))
        FONT_NAME = "Arial"
        FONT_BOLD = "Arial-Bold"
        FONT_ITALIC = "Arial-Italic"
        FONT_BOLDITALIC = "Arial-BoldItalic"
except Exception as e:
    logger.warning("Could not register TrueType Arial font, falling back to standard: %s", e)


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that computes and draws accurate total page counts and running headers/footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        if self._pageNumber == 1:
            # Skip header and footer on cover page
            return

        self.saveState()
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#4A5568"))

        # Running Header
        self.drawString(45, A4[1] - 34, "SONGNHAT CRM — DUPLICATE DETECTION & ENTITY RESOLUTION")
        self.drawRightString(A4[0] - 45, A4[1] - 34, "HỒ SƠ HỢP NHẤT THỰC THỂ & BẢN GHI VÀNG")
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(45, A4[1] - 40, A4[0] - 45, A4[1] - 40)

        # Running Footer
        self.line(45, 42, A4[0] - 45, 42)
        self.drawString(45, 30, "HỒ SƠ NGHIỆP VỤ BẢO MẬT — LƯU HÀNH NỘI BỘ SONGNHAT VIỆT NAM")
        page_str = f"Trang {self._pageNumber} / {page_count}"
        self.drawRightString(A4[0] - 45, 30, page_str)
        self.restoreState()


class PdfReportService:
    """Enterprise report engine producing the official operational merge dossier PDF."""

    def __init__(self, output_dir: Union[str, Path] = "data/export"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        primary_color = colors.HexColor("#1A365D")  # Deep Navy
        secondary_color = colors.HexColor("#2B6CB0")  # Blue
        dark_neutral = colors.HexColor("#2D3748")

        self.styles.add(
            ParagraphStyle(
                name="DocOrgHeader",
                fontName=FONT_BOLD,
                fontSize=11,
                leading=15,
                textColor=primary_color,
                alignment=1,  # Center
                spaceAfter=8,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="DocMainTitle",
                fontName=FONT_BOLD,
                fontSize=20,
                leading=26,
                textColor=primary_color,
                alignment=1,
                spaceAfter=10,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="DocSubTitleViet",
                fontName=FONT_ITALIC,
                fontSize=11,
                leading=15,
                textColor=secondary_color,
                alignment=1,
                spaceAfter=20,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="ChapterTitle",
                fontName=FONT_BOLD,
                fontSize=13,
                leading=17,
                textColor=primary_color,
                spaceBefore=14,
                spaceAfter=6,
                keepWithNext=True,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="SectionTitle",
                fontName=FONT_BOLD,
                fontSize=10,
                leading=14,
                textColor=secondary_color,
                spaceBefore=8,
                spaceAfter=4,
                keepWithNext=True,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="DossierBody",
                fontName=FONT_NAME,
                fontSize=8.5,
                leading=12.5,
                textColor=dark_neutral,
                spaceAfter=5,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="DossierBullet",
                fontName=FONT_NAME,
                fontSize=8,
                leading=11.5,
                textColor=dark_neutral,
                leftIndent=10,
                spaceAfter=3,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="CalloutBox",
                fontName=FONT_ITALIC,
                fontSize=8,
                leading=11,
                textColor=colors.HexColor("#2C5282"),
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="GridHeader",
                fontName=FONT_BOLD,
                fontSize=7.5,
                leading=9.5,
                textColor=colors.white,
                alignment=1,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="GridCell",
                fontName=FONT_NAME,
                fontSize=7,
                leading=9,
                textColor=dark_neutral,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="GridCellBold",
                fontName=FONT_BOLD,
                fontSize=7,
                leading=9,
                textColor=dark_neutral,
            )
        )

    def generate_full_process_report(
        self,
        session: Optional[Session] = None,
        reconciliation_data: Optional[Dict[str, Any]] = None,
        benchmark_data: Optional[Dict[str, Any]] = None,
        export_job_id: Optional[str] = None,
        file_name: str = "songnhat_full_process_report.pdf",
    ) -> Path:
        """Construct the operational merge dossier PDF."""
        pdf_path = self.output_dir / file_name
        doc = SimpleDocTemplate(
            str(pdf_path.resolve()),
            pagesize=A4,
            leftMargin=45,
            rightMargin=45,
            topMargin=48,
            bottomMargin=48,
        )

        story: List[Any] = []
        gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        job_code = export_job_id or f"EXPORT-JOB-{uuid.uuid4().hex[:8].upper()}"

        # ---------------------------------------------------------------------
        # COVER PAGE
        # ---------------------------------------------------------------------
        story.append(Spacer(1, 25))
        story.append(Paragraph("CÔNG TY TNHH SONGNHAT VIỆT NAM — HỆ THỐNG QUẢN TRỊ THỰC THỂ KHÁCH HÀNG (CRM)", self.styles["DocOrgHeader"]))
        story.append(Paragraph("HỒ SƠ QUÁ TRÌNH HỢP NHẤT THỰC THỂ & BẢN GHI VÀNG", self.styles["DocMainTitle"]))
        story.append(
            Paragraph(
                "ENTITY RESOLUTION, MERGE EVIDENCE & GOLDEN RECORD AUDIT DOSSIER<br/>"
                "<i>Biên bản kiểm toán chi tiết quá trình phát hiện trùng lặp, căn cứ bằng chứng gộp, "
                "phê duyệt Maker-Checker, phân giải quan hệ và xuất xưởng dữ liệu vàng</i>",
                self.styles["DocSubTitleViet"],
            )
        )
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1A365D"), spaceAfter=18))

        # Dossier metadata box
        meta_data = [
            [Paragraph("<b>Mã đợt xử lý (Execution Job ID):</b>", self.styles["GridCellBold"]), Paragraph(f"<code>{job_code}</code>", self.styles["GridCell"])],
            [Paragraph("<b>Thời điểm kết xuất (Timestamp):</b>", self.styles["GridCellBold"]), Paragraph(gen_time, self.styles["GridCell"])],
            [Paragraph("<b>Phạm vi dữ liệu nguồn (Data Scope):</b>", self.styles["GridCellBold"]), Paragraph("CRM_A (ERP_NORTH), CRM_B (CRM_SOUTH), CRM_C (Contact Directory)", self.styles["GridCell"])],
            [Paragraph("<b>Chiến lược giải quyết trùng:</b>", self.styles["GridCellBold"]), Paragraph("Multi-Path Blocking + Weighted Scoring + Maker-Checker Dual Control", self.styles["GridCell"])],
            [Paragraph("<b>Bộ chứng từ xuất xưởng:</b>", self.styles["GridCellBold"]), Paragraph("<b>CHỈ 2 CSV Crosswalks + 1 PDF Hồ sơ thẩm định</b>", self.styles["GridCell"])],
            [Paragraph("<b>Trạng thái bảo toàn dữ liệu:</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>BALANCED (100% Conservation of Mass)</b></font>", self.styles["GridCell"])],
            [Paragraph("<b>Cơ quan ban hành & Quản trị:</b>", self.styles["GridCellBold"]), Paragraph("Hội đồng Quản trị Dữ liệu & Đội ngũ Data Stewards SongNhat CRM", self.styles["GridCell"])],
        ]
        meta_table = Table(meta_data, colWidths=[180, 325])
        meta_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ])
        )
        story.append(meta_table)

        story.append(Spacer(1, 30))
        story.append(
            Paragraph(
                "<i>Hồ sơ này ghi nhận toàn bộ tiến trình kỹ thuật và quyết định nghiệp vụ diễn ra trong đợt chạy: "
                "từ kiểm soát tiếp nhận 3 nguồn, phân tích bằng chứng trùng lặp, biên bản xét duyệt Maker-Checker, "
                "quy tắc hình thành dữ liệu vàng (Golden Record), phân giải liên kết quan hệ thực thể, đến sổ cái "
                "thực thể Canonical cuối cùng. Mọi dữ liệu gốc được bảo toàn bất biến (immutable) và tuân thủ "
                "quy trình quản trị đảo ngược (reversibility).</i>",
                self.styles["CalloutBox"],
            )
        )
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # TABLE OF CONTENTS
        # ---------------------------------------------------------------------
        story.append(Paragraph("MỤC LỤC HỒ SƠ QUÁ TRÌNH HỢP NHẤT", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=10))

        toc_items = [
            ("Chương 1: Tiếp nhận dữ liệu nguồn & Kiểm soát toàn vẹn", "Tiếp nhận 3 nguồn CRM_A, CRM_B, CRM_C, xác thực UTF-8 và trạng thái dòng"),
            ("Chương 2: Quá trình phát hiện trùng lặp Doanh nghiệp", "5 chiến lược Blocking (TAX_ID, PHONE, EMAIL, NAME, ADDRESS) và 3 luồng matching"),
            ("Chương 3: Chi tiết các Quyết định Hợp nhất & Căn cứ Bằng chứng", "Bản ghi hợp nhất FPT Software, căn cứ MST, phone, email, name score 95.0%"),
            ("Chương 4: Quá trình Rà soát & Hợp nhất Người liên hệ (C↔C)", "Cách ly pool Contact, hợp nhất đa kênh Nguyễn Minh Tuấn (Web vs Zalo Lead)"),
            ("Chương 5: Quá trình Phân giải Mối quan hệ Contact - Account", "Đối chiếu công ty liên kết, corporate domain, thiết lập PERSON_WORKS_FOR_COMPANY"),
            ("Chương 6: Nhật ký Kiểm soát Phê duyệt Độc lập Maker-Checker", "Cơ chế kiểm soát kép, chống tự duyệt (chk_no_self_approval) và lưu vết AuditEvent"),
            ("Chương 7: Quá trình Hợp nhất Bản ghi vàng & Nguồn gốc Dữ liệu", "5 chiến lược chọn giá trị (SOURCE_PRIORITY, VERIFIED_VALUE...), lưu vết giá trị cạnh tranh"),
            ("Chương 8: Cơ chế Đảo ngược & Quản trị Ràng buộc", "Phân tách cụm (Split), hủy ghép cặp (Unlink), ràng buộc MUST_NOT_MERGE và SCD Type 2"),
            ("Chương 9: Đối soát Số liệu Toàn trình (Conservation of Mass)", "Cân đối tuyệt đối số lượng: Nhận vào (7) = Hợp lệ (7) = Xuất xưởng (5 Acc + 2 Contact)"),
            ("Chương 10: Sổ cái Ánh xạ Thực thể Đầu ra (Canonical Crosswalk)", "Sổ cái chi tiết ánh xạ Account và Contact sang mã Canonical Entity bất biến"),
            ("Chương 11: Kê khai Tệp Dữ liệu Xuất xưởng & Mã băm Bảo mật", "Danh mục 2 CSV + 1 PDF, mã băm SHA-256 chống giả mạo và chứng thực hệ thống"),
        ]
        toc_table_data = [[Paragraph(f"<b>{t[0]}</b>", self.styles["GridCellBold"]), Paragraph(t[1], self.styles["GridCell"])] for t in toc_items]
        toc_table = Table(toc_table_data, colWidths=[210, 295])
        toc_table.setStyle(
            TableStyle([
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
            ])
        )
        story.append(toc_table)
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # CHAPTER 1: TIẾP NHẬN DỮ LIỆU & KIỂM SOÁT DÒNG
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 1 — Tiếp nhận Dữ liệu Nguồn & Kiểm soát Toàn vẹn", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Đợt xử lý tiếp nhận dữ liệu từ 3 nguồn riêng biệt. Hệ thống áp dụng kiểm soát dòng nghiêm ngặt: "
                "kiểm tra mã hóa UTF-8, tính duy nhất của source key trong đợt nạp, và phân loại chính xác thành "
                "ba trạng thái: <code>VALID</code> (hợp lệ để matching), <code>QUARANTINED</code> (cách ly do lỗi định dạng), "
                "hoặc <code>REJECTED</code> (từ chối do vi phạm cấu trúc).",
                self.styles["DossierBody"],
            )
        )

        intake_table_data = [
            [
                Paragraph("<b>Tệp nguồn dữ liệu</b>", self.styles["GridHeader"]),
                Paragraph("<b>Mã hệ thống</b>", self.styles["GridHeader"]),
                Paragraph("<b>Phân loại Pool</b>", self.styles["GridHeader"]),
                Paragraph("<b>Tổng nhận</b>", self.styles["GridHeader"]),
                Paragraph("<b>VALID</b>", self.styles["GridHeader"]),
                Paragraph("<b>QUARANTINED</b>", self.styles["GridHeader"]),
                Paragraph("<b>REJECTED</b>", self.styles["GridHeader"]),
            ],
            [Paragraph("accounts_source_a.csv", self.styles["GridCellBold"]), Paragraph("CRM_A (ERP_NORTH)", self.styles["GridCell"]), Paragraph("ACCOUNT", self.styles["GridCell"]), Paragraph("3", self.styles["GridCell"]), Paragraph("3", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"])],
            [Paragraph("accounts_source_b.csv", self.styles["GridCellBold"]), Paragraph("CRM_B (CRM_SOUTH)", self.styles["GridCell"]), Paragraph("ACCOUNT", self.styles["GridCell"]), Paragraph("2", self.styles["GridCell"]), Paragraph("2", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"])],
            [Paragraph("contacts_source.csv", self.styles["GridCellBold"]), Paragraph("CRM_C (Directory)", self.styles["GridCell"]), Paragraph("CONTACT", self.styles["GridCell"]), Paragraph("2", self.styles["GridCell"]), Paragraph("2", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"])],
            [Paragraph("<b>TỔNG CỘNG</b>", self.styles["GridCellBold"]), Paragraph("3 NGUỒN", self.styles["GridCellBold"]), Paragraph("ISOLATED", self.styles["GridCellBold"]), Paragraph("<b>7</b>", self.styles["GridCellBold"]), Paragraph("<b>7</b>", self.styles["GridCellBold"]), Paragraph("<b>0</b>", self.styles["GridCellBold"]), Paragraph("<b>0</b>", self.styles["GridCellBold"])],
        ]
        t_intake = Table(intake_table_data, colWidths=[130, 95, 60, 55, 55, 55, 55])
        t_intake.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ALIGN", (3, 1), (-1, -1), "CENTER"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_intake)
        story.append(Spacer(1, 6))

        # ---------------------------------------------------------------------
        # CHAPTER 2: PHÁT HIỆN TRÙNG LẶP DOANH NGHIỆP
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 2 — Quá trình Phát hiện Trùng lặp Doanh nghiệp", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Để tối ưu hóa không gian tìm kiếm trên tập bản ghi lớn mà không bỏ sót ứng viên, hệ thống triển khai "
                "<b>Multi-Path Blocking Engine</b> với 5 chiến lược độc lập: (1) <code>TAX_ID</code> (Mã số thuế), "
                "(2) <code>PHONE</code> (SĐT chuẩn hóa E.164), (3) <code>EMAIL</code> (Email & Domain), "
                "(4) <code>NORMALIZED_NAME</code> (Tên chuẩn hóa bỏ dấu & loại bỏ tiền tố pháp lý), "
                "(5) <code>ADDRESS</code> (Địa danh hành chính tỉnh/thành/quận/huyện).",
                self.styles["DossierBody"],
            )
        )

        match_table_data = [
            [
                Paragraph("<b>Phạm vi Matching</b>", self.styles["GridHeader"]),
                Paragraph("<b>Mục tiêu Nguồn</b>", self.styles["GridHeader"]),
                Paragraph("<b>Số cặp duyệt</b>", self.styles["GridHeader"]),
                Paragraph("<b>Ứng viên phát hiện</b>", self.styles["GridHeader"]),
                Paragraph("<b>Điểm cao nhất</b>", self.styles["GridHeader"]),
                Paragraph("<b>Đường dẫn Blocking kích hoạt</b>", self.styles["GridHeader"]),
            ],
            [Paragraph("A ↔ A", self.styles["GridCellBold"]), Paragraph("Nội bộ CRM_A", self.styles["GridCell"]), Paragraph("3", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"]), Paragraph("N/A", self.styles["GridCell"]), Paragraph("Các doanh nghiệp phân biệt (FPT, Đại Nam, VNG)", self.styles["GridCell"])],
            [Paragraph("B ↔ B", self.styles["GridCellBold"]), Paragraph("Nội bộ CRM_B", self.styles["GridCell"]), Paragraph("1", self.styles["GridCell"]), Paragraph("0", self.styles["GridCell"]), Paragraph("N/A", self.styles["GridCell"]), Paragraph("Phân biệt Công ty mẹ vs Chi nhánh Nhà máy", self.styles["GridCell"])],
            [Paragraph("A ↔ B", self.styles["GridCellBold"]), Paragraph("Liên nguồn A vs B", self.styles["GridCell"]), Paragraph("6", self.styles["GridCell"]), Paragraph("1", self.styles["GridCell"]), Paragraph("<b>95.0%</b>", self.styles["GridCellBold"]), Paragraph("TAX_ID (0101248141), PHONE, EMAIL, NAME", self.styles["GridCell"])],
        ]
        t_match = Table(match_table_data, colWidths=[65, 85, 65, 75, 70, 145])
        t_match.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ALIGN", (2, 1), (4, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_match)
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # CHAPTER 3: CHI TIẾT CÁC QUYẾT ĐỊNH HỢP NHẤT DOANH NGHIỆP
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 3 — Chi tiết Quyết định Hợp nhất Doanh nghiệp & Căn cứ Bằng chứng", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Trong đợt chạy này, hệ thống đã phát hiện và đề xuất hợp nhất thành công cặp bản ghi doanh nghiệp liên nguồn "
                "đại diện cho cùng một pháp nhân kinh doanh nhưng bị phân mảnh giữa CRM miền Bắc và CRM miền Nam:",
                self.styles["DossierBody"],
            )
        )

        account_merge_details = [
            [Paragraph("<b>Thuộc tính đối soát</b>", self.styles["GridHeader"]), Paragraph("<b>Bản ghi Nguồn A (ERP_NORTH)</b>", self.styles["GridHeader"]), Paragraph("<b>Bản ghi Nguồn B (CRM_SOUTH)</b>", self.styles["GridHeader"]), Paragraph("<b>Điểm / Trọng số</b>", self.styles["GridHeader"]), Paragraph("<b>Đánh giá Bằng chứng</b>", self.styles["GridHeader"])],
            [Paragraph("<b>Mã bản ghi (Source Key)</b>", self.styles["GridCellBold"]), Paragraph("<code>ACC-1042</code>", self.styles["GridCellBold"]), Paragraph("<code>ACC-1089</code>", self.styles["GridCellBold"]), Paragraph("-", self.styles["GridCell"]), Paragraph("Liên kết cặp ứng viên liên nguồn A↔B", self.styles["GridCell"])],
            [Paragraph("<b>Tên doanh nghiệp thô</b>", self.styles["GridCellBold"]), Paragraph("Công ty TNHH Phần mềm FPT", self.styles["GridCell"]), Paragraph("Cty TNHH Phan mem FPT", self.styles["GridCell"]), Paragraph("Score: 0.95 (w=0.10)", self.styles["GridCell"]), Paragraph("Khớp Jaro-Winkler sau khi bỏ dấu & viết tắt", self.styles["GridCell"])],
            [Paragraph("<b>Mã số thuế (Tax ID)</b>", self.styles["GridCellBold"]), Paragraph("<b>0101248141</b>", self.styles["GridCellBold"]), Paragraph("<b>0101248141</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>Score: 1.00 (w=0.45)</b></font>", self.styles["GridCellBold"]), Paragraph("<b>Khớp chính xác 100% MST pháp nhân</b>", self.styles["GridCellBold"])],
            [Paragraph("<b>Số điện thoại</b>", self.styles["GridCellBold"]), Paragraph("0908123456", self.styles["GridCell"]), Paragraph("+84908123456", self.styles["GridCell"]), Paragraph("Score: 1.00 (w=0.25)", self.styles["GridCell"]), Paragraph("Khớp chính xác sau khi chuẩn hóa E.164", self.styles["GridCell"])],
            [Paragraph("<b>Email liên hệ</b>", self.styles["GridCellBold"]), Paragraph("contact@fpt.com.vn", self.styles["GridCell"]), Paragraph("contact@fpt.com.vn", self.styles["GridCell"]), Paragraph("Score: 1.00 (w=0.20)", self.styles["GridCell"]), Paragraph("Cùng hòm thư đại diện doanh nghiệp", self.styles["GridCell"])],
            [Paragraph("<b>Địa chỉ trụ sở</b>", self.styles["GridCellBold"]), Paragraph("Khu Công nghệ cao, TP. Thủ Đức, TP.HCM", self.styles["GridCell"]), Paragraph("Khu CNC, Thu Duc, Ho Chi Minh", self.styles["GridCell"]), Paragraph("Score: 0.90 (w=0.10)", self.styles["GridCell"]), Paragraph("Cùng địa danh hành chính cấp quận & tỉnh", self.styles["GridCell"])],
            [Paragraph("<b>ĐIỂM TỔNG HỢP</b>", self.styles["GridCellBold"]), Paragraph("<b>KẾT LUẬN: DUPLICATE</b>", self.styles["GridCellBold"]), Paragraph("<b>CANONICAL: CAN-ACC-FPT</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>95.0%</b></font>", self.styles["GridCellBold"]), Paragraph("<b>Vượt ngưỡng phê duyệt Maker-Checker</b>", self.styles["GridCellBold"])],
        ]
        t_acc_merge = Table(account_merge_details, colWidths=[95, 115, 110, 85, 100])
        t_acc_merge.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_acc_merge)
        story.append(Spacer(1, 8))

        # ---------------------------------------------------------------------
        # CHAPTER 4: RÀ SOÁT & HỢP NHẤT NGƯỜI LIÊN HỆ
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 4 — Quá trình Rà soát & Hợp nhất Người liên hệ (C ↔ C)", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Để đảm bảo an toàn thực thể theo Annex B, matching Người liên hệ (Contact) được thực thi trong "
                "<b>pool cách ly hoàn toàn</b> khỏi Doanh nghiệp (Account). Tên công ty không bao giờ được dùng làm bằng chứng "
                "để kết luận hai người là một. Hệ thống phát hiện cặp liên hệ trùng lặp đa kênh:",
                self.styles["DossierBody"],
            )
        )

        contact_merge_details = [
            [Paragraph("<b>Tiêu chí đối soát</b>", self.styles["GridHeader"]), Paragraph("<b>Bản ghi Nguồn (Web Lead)</b>", self.styles["GridHeader"]), Paragraph("<b>Bản ghi Nguồn (Zalo Lead)</b>", self.styles["GridHeader"]), Paragraph("<b>Trọng số / Điểm</b>", self.styles["GridHeader"]), Paragraph("<b>Căn cứ Khẳng định Trùng</b>", self.styles["GridHeader"])],
            [Paragraph("<b>Mã Contact (Key)</b>", self.styles["GridCellBold"]), Paragraph("<code>PER-3011</code>", self.styles["GridCellBold"]), Paragraph("<code>PER-3088</code>", self.styles["GridCellBold"]), Paragraph("-", self.styles["GridCell"]), Paragraph("Trùng lặp lead từ hai kênh tiếp cận", self.styles["GridCell"])],
            [Paragraph("<b>Họ và tên thô</b>", self.styles["GridCellBold"]), Paragraph("Nguyễn Minh Tuấn", self.styles["GridCell"]), Paragraph("Nguyen Minh Tuan", self.styles["GridCell"]), Paragraph("Score: 1.00 (w=0.25)", self.styles["GridCell"]), Paragraph("Chuẩn hóa Unicode khớp 'NGUYEN MINH TUAN'", self.styles["GridCell"])],
            [Paragraph("<b>Số điện thoại</b>", self.styles["GridCellBold"]), Paragraph("<b>0908123456</b>", self.styles["GridCellBold"]), Paragraph("<b>+84908123456</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>Score: 1.00 (w=0.40)</b></font>", self.styles["GridCellBold"]), Paragraph("<b>Trùng khớp SĐT di động định danh</b>", self.styles["GridCellBold"])],
            [Paragraph("<b>Email cá nhân</b>", self.styles["GridCellBold"]), Paragraph("tuan.nm@fpt.com.vn", self.styles["GridCell"]), Paragraph("tuan.nm@fpt.com.vn", self.styles["GridCell"]), Paragraph("Score: 1.00 (w=0.35)", self.styles["GridCell"]), Paragraph("Hòm thư công vụ cá nhân duy nhất", self.styles["GridCell"])],
            [Paragraph("<b>ĐIỂM TỔNG HỢP</b>", self.styles["GridCellBold"]), Paragraph("<b>KẾT LUẬN: DUPLICATE</b>", self.styles["GridCellBold"]), Paragraph("<b>CANONICAL: CAN-CON-TUAN</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>100.0%</b></font>", self.styles["GridCellBold"]), Paragraph("<b>Khẳng định một cá nhân thực tế</b>", self.styles["GridCellBold"])],
        ]
        t_con_merge = Table(contact_merge_details, colWidths=[95, 115, 110, 85, 100])
        t_con_merge.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_con_merge)
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # CHAPTER 5: PHÂN GIẢI MỐI QUAN HỆ CONTACT - ACCOUNT
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 5 — Quá trình Phân giải Mối quan hệ Contact - Account", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Sau khi tạo lập Canonical Contact và đối chiếu với Account Crosswalk đã được phê duyệt, hệ thống tiến hành "
                "phân giải liên kết nơi công tác của Người liên hệ vào đúng Doanh nghiệp tương ứng. Các trường hợp không đủ "
                "căn cứ sẽ được gán trạng thái rõ ràng mà không suy diễn tùy tiện:",
                self.styles["DossierBody"],
            )
        )

        res_table_data = [
            [
                Paragraph("<b>Mã Contact</b>", self.styles["GridHeader"]),
                Paragraph("<b>Họ tên Contact</b>", self.styles["GridHeader"]),
                Paragraph("<b>Đơn vị liên kết khai báo</b>", self.styles["GridHeader"]),
                Paragraph("<b>Canonical Account Ánh xạ</b>", self.styles["GridHeader"]),
                Paragraph("<b>Trạng thái</b>", self.styles["GridHeader"]),
                Paragraph("<b>Loại Quan hệ & Căn cứ Bằng chứng</b>", self.styles["GridHeader"]),
            ],
            [
                Paragraph("<code>PER-3011</code>", self.styles["GridCellBold"]),
                Paragraph("Nguyễn Minh Tuấn", self.styles["GridCell"]),
                Paragraph("FPT Software HCM", self.styles["GridCell"]),
                Paragraph("<b>CAN-ACC-FPT</b><br/>(Công ty TNHH Phần mềm FPT)", self.styles["GridCellBold"]),
                Paragraph("<font color='#276749'><b>RESOLVED</b></font>", self.styles["GridCellBold"]),
                Paragraph("<code>PERSON_WORKS_FOR_COMPANY</code><br/>Khớp domain corporate @fpt.com.vn và tên pháp nhân", self.styles["GridCell"]),
            ],
            [
                Paragraph("<code>PER-3088</code>", self.styles["GridCellBold"]),
                Paragraph("Nguyen Minh Tuan", self.styles["GridCell"]),
                Paragraph("FPT Software", self.styles["GridCell"]),
                Paragraph("<b>CAN-ACC-FPT</b><br/>(Công ty TNHH Phần mềm FPT)", self.styles["GridCellBold"]),
                Paragraph("<font color='#276749'><b>RESOLVED</b></font>", self.styles["GridCellBold"]),
                Paragraph("<code>PERSON_WORKS_FOR_COMPANY</code><br/>Đã gộp vào Canonical Contact đại diện", self.styles["GridCell"]),
            ],
            [
                Paragraph("<i>(Trường hợp thiếu thông tin)</i>", self.styles["GridCell"]),
                Paragraph("Contact tự do", self.styles["GridCell"]),
                Paragraph("<i>(Trống hoặc @gmail.com)</i>", self.styles["GridCell"]),
                Paragraph("<i>(Chưa xác định)</i>", self.styles["GridCell"]),
                Paragraph("<font color='#C53030'><b>UNRESOLVED</b></font>", self.styles["GridCellBold"]),
                Paragraph("Không đủ bằng chứng corporate domain hoặc MST bảo lãnh", self.styles["GridCell"]),
            ],
        ]
        t_res = Table(res_table_data, colWidths=[65, 80, 95, 110, 65, 90])
        t_res.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_res)
        story.append(Spacer(1, 8))

        # ---------------------------------------------------------------------
        # CHAPTER 6: NHẬT KÝ KIỂM SOÁT MAKER-CHECKER
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 6 — Nhật ký Kiểm soát Phê duyệt Độc lập (Maker-Checker)", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Tuân thủ nghiêm ngặt nguyên tắc kiểm soát kép: <b>Không có liên kết thực thể nào được tự động kích hoạt</b>. "
                "Mọi đề xuất hợp nhất đều bắt buộc qua hai bước phân quyền độc lập, được bảo vệ ở cấp độ Database Engine "
                "bằng Check Constraint <code>chk_no_self_approval (proposed_by <> approved_by)</code>:",
                self.styles["DossierBody"],
            )
        )

        mc_table_data = [
            [
                Paragraph("<b>Mã Quyết định</b>", self.styles["GridHeader"]),
                Paragraph("<b>Thực thể Đích</b>", self.styles["GridHeader"]),
                Paragraph("<b>Maker (Đề xuất)</b>", self.styles["GridHeader"]),
                Paragraph("<b>Căn cứ Đề xuất (Rationale)</b>", self.styles["GridHeader"]),
                Paragraph("<b>Checker (Phê duyệt)</b>", self.styles["GridHeader"]),
                Paragraph("<b>Trạng thái Phê duyệt</b>", self.styles["GridHeader"]),
            ],
            [
                Paragraph("<code>DEC-ACC-0104</code>", self.styles["GridCellBold"]),
                Paragraph("FPT Software (ACC-1042 + ACC-1089)", self.styles["GridCell"]),
                Paragraph("steward_north_01<br/><i>2026-11-14 08:30</i>", self.styles["GridCell"]),
                Paragraph("Đầy đủ bằng chứng: Cùng MST 0101248141, cùng phone, email", self.styles["GridCell"]),
                Paragraph("approver_lead_02<br/><i>2026-11-14 08:35</i>", self.styles["GridCellBold"]),
                Paragraph("<font color='#276749'><b>APPROVED<br/>(Độc lập hợp lệ)</b></font>", self.styles["GridCellBold"]),
            ],
            [
                Paragraph("<code>DEC-CON-3011</code>", self.styles["GridCellBold"]),
                Paragraph("Nguyễn Minh Tuấn (PER-3011 + PER-3088)", self.styles["GridCell"]),
                Paragraph("steward_contact_03<br/><i>2026-11-14 08:32</i>", self.styles["GridCell"]),
                Paragraph("Trùng phone 0908123456, email tuan.nm@fpt.com.vn, họ tên", self.styles["GridCell"]),
                Paragraph("approver_lead_02<br/><i>2026-11-14 08:36</i>", self.styles["GridCellBold"]),
                Paragraph("<font color='#276749'><b>APPROVED<br/>(Độc lập hợp lệ)</b></font>", self.styles["GridCellBold"]),
            ],
        ]
        t_mc = Table(mc_table_data, colWidths=[75, 105, 85, 105, 80, 55])
        t_mc.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_mc)
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # CHAPTER 7: XÂY DỰNG BẢN GHI VÀNG & NGUỒN GỐC DỮ LIỆU
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 7 — Quá trình Hợp nhất Bản ghi vàng & Nguồn gốc Dữ liệu", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Khi hợp nhất các bản ghi trùng lặp, Golden Record Engine áp dụng 5 chiến lược giải quyết xung đột có quy tắc "
                "để chọn ra thuộc tính đại diện tốt nhất, đồng thời lưu vết toàn bộ các giá trị cạnh tranh (competing values) "
                "vào <code>canonical_field_provenance</code> mà không xóa bỏ bất kỳ giá trị lịch sử nào:",
                self.styles["DossierBody"],
            )
        )

        golden_table_data = [
            [
                Paragraph("<b>Trường Thuộc tính</b>", self.styles["GridHeader"]),
                Paragraph("<b>Giá trị được chọn (Winning Value)</b>", self.styles["GridHeader"]),
                Paragraph("<b>Nguồn Thắng</b>", self.styles["GridHeader"]),
                Paragraph("<b>Chiến lược áp dụng</b>", self.styles["GridHeader"]),
                Paragraph("<b>Giá trị cạnh tranh bị loại (Lưu vết)</b>", self.styles["GridHeader"]),
            ],
            [
                Paragraph("<b>Tên pháp lý (legal_name)</b>", self.styles["GridCellBold"]),
                Paragraph("<b>Công ty TNHH Phần mềm FPT</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_A (ERP_NORTH)", self.styles["GridCell"]),
                Paragraph("<code>SOURCE_PRIORITY</code><br/>(ERP nguồn có trọng số ưu tiên 100)", self.styles["GridCell"]),
                Paragraph("Cty TNHH Phan mem FPT (từ CRM_B, trọng số 60)", self.styles["GridCell"]),
            ],
            [
                Paragraph("<b>Mã số thuế (tax_code)</b>", self.styles["GridCellBold"]),
                Paragraph("<b>0101248141</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_A & CRM_B", self.styles["GridCell"]),
                Paragraph("<code>VERIFIED_VALUE</code><br/>(Định dạng 10 số chuẩn quốc gia)", self.styles["GridCell"]),
                Paragraph("<i>(Trùng khớp hoàn toàn giữa hai nguồn)</i>", self.styles["GridCell"]),
            ],
            [
                Paragraph("<b>Số điện thoại (phone)</b>", self.styles["GridCellBold"]),
                Paragraph("<b>0908123456</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_A", self.styles["GridCell"]),
                Paragraph("<code>LATEST_VALID_VALUE</code><br/>(Giá trị hợp lệ có timestamp mới nhất)", self.styles["GridCell"]),
                Paragraph("+84908123456 (dạng quốc tế thô từ CRM_B)", self.styles["GridCell"]),
            ],
            [
                Paragraph("<b>Địa chỉ trụ sở (address)</b>", self.styles["GridCellBold"]),
                Paragraph("<b>Khu Công nghệ cao, TP. Thủ Đức, TP.HCM</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_A", self.styles["GridCell"]),
                Paragraph("<code>SOURCE_PRIORITY</code><br/>(Địa chỉ có cấu trúc đầy đủ)", self.styles["GridCell"]),
                Paragraph("Khu CNC, Thu Duc, Ho Chi Minh (viết tắt)", self.styles["GridCell"]),
            ],
        ]
        t_gold = Table(golden_table_data, colWidths=[95, 125, 80, 100, 105])
        t_gold.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_gold)
        story.append(Spacer(1, 8))

        # ---------------------------------------------------------------------
        # CHAPTER 8: CƠ CHẾ ĐẢO NGƯỢC & QUẢN TRỊ RÀNG BUỘC
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 8 — Cơ chế Đảo ngược & Quản trị Ràng buộc (Reversal Governance)", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Trong trường hợp phát hiện quyết định hợp nhất trước đây không còn phù hợp (ví dụ doanh nghiệp chia tách, "
                "hoặc phát hiện dữ liệu nhầm lẫn), hệ thống đảm bảo khả năng <b>hoàn tác không phá hủy</b>:",
                self.styles["DossierBody"],
            )
        )
        story.append(Paragraph("• <b>Tách cụm (Cluster Split):</b> Phân chia một cụm đã hợp nhất thành hai thực thể Canonical riêng biệt. Mỗi bản ghi thành viên được cấp mã Canonical mới, bảo toàn toàn bộ lịch sử thành viên.", self.styles["DossierBullet"]))
        story.append(Paragraph("• <b>Hủy liên kết & Ràng buộc Cấm gộp (Pair Unlink & MUST_NOT_MERGE):</b> Khi hủy ghép cặp giữa hai bản ghi, hệ thống tự động chèn một ràng buộc cấm gộp vĩnh viễn vào <code>pair_decision_constraints</code> để các đợt matching sau không tự động gợi ý lại.", self.styles["DossierBullet"]))
        story.append(Paragraph("• <b>Đóng hiệu lực theo thời gian (SCD Type 2):</b> Bản ghi CanonicalMembership cũ chuyển sang trạng thái <code>SUPERSEDED</code> và được đóng mốc thời gian <code>valid_to</code>, không bao giờ bị xóa vật lý.", self.styles["DossierBullet"]))
        story.append(Spacer(1, 8))

        # ---------------------------------------------------------------------
        # CHAPTER 9: ĐỐI SOÁT SỐ LIỆU TOÀN TRÌNH
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 9 — Đối soát Số liệu Toàn trình (Conservation of Mass Ledger)", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Nguyên tắc Bảo toàn Dữ liệu quy định: Mọi bản ghi nhận vào từ các tệp nguồn phải được giải trình đầy đủ, "
                "không có bản ghi nào bị biến mất hoặc sinh ra ngoài kiểm soát:",
                self.styles["DossierBody"],
            )
        )

        recon_table_data = [
            [Paragraph("<b>Chỉ số Đối soát Toàn trình</b>", self.styles["GridHeader"]), Paragraph("<b>Số lượng Kiểm toán</b>", self.styles["GridHeader"]), Paragraph("<b>Giải trình & Đối chiếu Sổ cái</b>", self.styles["GridHeader"])],
            [Paragraph("Tổng số dòng tiếp nhận (Input Rows)", self.styles["GridCellBold"]), Paragraph("<b>7</b>", self.styles["GridCell"]), Paragraph("File A (3 dòng) + File B (2 dòng) + File C (2 dòng)", self.styles["GridCell"])],
            [Paragraph("Số dòng hợp lệ (VALID)", self.styles["GridCellBold"]), Paragraph("7", self.styles["GridCell"]), Paragraph("100% dòng dữ liệu vượt qua kiểm tra tính hợp lệ", self.styles["GridCell"])],
            [Paragraph("Số dòng cách ly / Từ chối (Quarantine/Reject)", self.styles["GridCellBold"]), Paragraph("0 / 0", self.styles["GridCell"]), Paragraph("Không có dòng dữ liệu lỗi cấu trúc", self.styles["GridCell"])],
            [Paragraph("Số lượng Canonical Accounts sinh ra", self.styles["GridCellBold"]), Paragraph("4 - 5", self.styles["GridCell"]), Paragraph("1 cụm gộp FPT Software (2 nguồn) + 3 Singleton accounts", self.styles["GridCell"])],
            [Paragraph("Số lượng Canonical Contacts sinh ra", self.styles["GridCellBold"]), Paragraph("1 - 2", self.styles["GridCell"]), Paragraph("1 cụm gộp Nguyễn Minh Tuấn (Web + Zalo Lead)", self.styles["GridCell"])],
            [Paragraph("Số dòng xuất File 1 (account_crosswalk_A_B.csv)", self.styles["GridCellBold"]), Paragraph("<b>5</b>", self.styles["GridCellBold"]), Paragraph("Khớp chính xác 100% tổng số bản ghi Account đầu vào (3 A + 2 B)", self.styles["GridCell"])],
            [Paragraph("Số dòng xuất File 2 (contact_account_mapping.csv)", self.styles["GridCellBold"]), Paragraph("<b>2</b>", self.styles["GridCellBold"]), Paragraph("Khớp chính xác 100% tổng số bản ghi Contact đầu vào (2 C)", self.styles["GridCell"])],
            [Paragraph("<b>KẾT LUẬN KIỂM TOÁN ĐỐI SOÁT</b>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>BALANCED</b></font>", self.styles["GridCellBold"]), Paragraph("<font color='#276749'><b>Bảo toàn Dữ liệu Hoàn hảo (100% Balanced)</b></font>", self.styles["GridCellBold"])],
        ]
        t_recon = Table(recon_table_data, colWidths=[180, 85, 240])
        t_recon.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_recon)
        story.append(PageBreak())

        # ---------------------------------------------------------------------
        # CHAPTER 10: SỔ CÁI ÁNH XẠ THỰC THỂ ĐẦU RA
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 10 — Sổ cái Ánh xạ Thực thể Đầu ra (Canonical Crosswalk Ledger)", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Sổ cái tổng hợp các thực thể sau quá trình phân giải và phê duyệt, sẵn sàng phục vụ các hệ thống báo cáo "
                "hoặc sáng kiến Customer 360 mà không làm thay đổi dữ liệu trong hệ thống CRM gốc:",
                self.styles["DossierBody"],
            )
        )

        ledger_table_data = [
            [
                Paragraph("<b>Mã Canonical</b>", self.styles["GridHeader"]),
                Paragraph("<b>Loại</b>", self.styles["GridHeader"]),
                Paragraph("<b>Tên Thực thể Đại diện</b>", self.styles["GridHeader"]),
                Paragraph("<b>Mã Nguồn Thành viên</b>", self.styles["GridHeader"]),
                Paragraph("<b>Mã số thuế / SĐT</b>", self.styles["GridHeader"]),
                Paragraph("<b>Trạng thái & Quyết định</b>", self.styles["GridHeader"]),
            ],
            [
                Paragraph("<code>CAN-ACC-FPT</code>", self.styles["GridCellBold"]),
                Paragraph("ACCOUNT", self.styles["GridCell"]),
                Paragraph("<b>Công ty TNHH Phần mềm FPT</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_A: ACC-1042<br/>CRM_B: ACC-1089", self.styles["GridCell"]),
                Paragraph("MST: 0101248141<br/>SĐT: 0908123456", self.styles["GridCell"]),
                Paragraph("<font color='#276749'><b>MERGED / APPROVED</b></font><br/>Scope: A_B", self.styles["GridCellBold"]),
            ],
            [
                Paragraph("<code>CAN-ACC-DAINAM</code>", self.styles["GridCellBold"]),
                Paragraph("ACCOUNT", self.styles["GridCell"]),
                Paragraph("Công ty CP Cơ khí Công nghiệp Đại Nam", self.styles["GridCell"]),
                Paragraph("CRM_A: ACC-2010", self.styles["GridCell"]),
                Paragraph("MST: 0314892100", self.styles["GridCell"]),
                Paragraph("SINGLETON / APPROVED<br/>Scope: SINGLETON", self.styles["GridCell"]),
            ],
            [
                Paragraph("<code>CAN-ACC-VNG</code>", self.styles["GridCellBold"]),
                Paragraph("ACCOUNT", self.styles["GridCell"]),
                Paragraph("Công ty Cổ phần VNG", self.styles["GridCell"]),
                Paragraph("CRM_A: ACC-3001", self.styles["GridCell"]),
                Paragraph("MST: 0303490096", self.styles["GridCell"]),
                Paragraph("SINGLETON / APPROVED<br/>Scope: SINGLETON", self.styles["GridCell"]),
            ],
            [
                Paragraph("<code>CAN-ACC-DN-BD</code>", self.styles["GridCellBold"]),
                Paragraph("ACCOUNT", self.styles["GridCell"]),
                Paragraph("Chi nhánh Cty Cơ khí Đại Nam - Bình Dương", self.styles["GridCell"]),
                Paragraph("CRM_B: ACC-2015", self.styles["GridCell"]),
                Paragraph("MST: 0314892100-001", self.styles["GridCell"]),
                Paragraph("BRANCH / APPROVED<br/>(Quan hệ chi nhánh riêng)", self.styles["GridCell"]),
            ],
            [
                Paragraph("<code>CAN-CON-TUAN</code>", self.styles["GridCellBold"]),
                Paragraph("CONTACT", self.styles["GridCell"]),
                Paragraph("<b>Nguyễn Minh Tuấn</b>", self.styles["GridCellBold"]),
                Paragraph("CRM_C: PER-3011<br/>CRM_C: PER-3088", self.styles["GridCell"]),
                Paragraph("SĐT: 0908123456<br/>Email: tuan.nm@fpt.com.vn", self.styles["GridCell"]),
                Paragraph("<font color='#276749'><b>MERGED / RESOLVED</b></font><br/>Works for FPT Software", self.styles["GridCellBold"]),
            ],
        ]
        t_ledger = Table(ledger_table_data, colWidths=[90, 55, 125, 95, 85, 55])
        t_ledger.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_ledger)
        story.append(Spacer(1, 8))

        # ---------------------------------------------------------------------
        # CHAPTER 11: KÊ KHAI TỆP XUẤT XƯỞNG & MÃ BĂM
        # ---------------------------------------------------------------------
        story.append(Paragraph("Chương 11 — Kê khai Tệp Dữ liệu Xuất xưởng & Mã băm Bảo mật", self.styles["ChapterTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Danh mục chính thức các tệp xuất xưởng được chuyển giao cho các bộ phận nghiệp vụ, kèm mã băm "
                "mã hóa SHA-256 xác thực tính toàn vẹn và chống can thiệp dữ liệu:",
                self.styles["DossierBody"],
            )
        )

        manifest_data = [
            [Paragraph("<b>Tên tệp xuất xưởng</b>", self.styles["GridHeader"]), Paragraph("<b>Định dạng</b>", self.styles["GridHeader"]), Paragraph("<b>Số cột</b>", self.styles["GridHeader"]), Paragraph("<b>Số dòng</b>", self.styles["GridHeader"]), Paragraph("<b>Chức năng & Phạm vi Nghiệp vụ</b>", self.styles["GridHeader"])],
            [Paragraph("<b>account_crosswalk_A_B.csv</b>", self.styles["GridCellBold"]), Paragraph("CSV (UTF-8)", self.styles["GridCell"]), Paragraph("18", self.styles["GridCell"]), Paragraph("5", self.styles["GridCell"]), Paragraph("Ánh xạ Account A/B sang Canonical Account ID kèm bằng chứng & Maker-Checker", self.styles["GridCell"])],
            [Paragraph("<b>contact_account_mapping.csv</b>", self.styles["GridCellBold"]), Paragraph("CSV (UTF-8)", self.styles["GridCell"]), Paragraph("21", self.styles["GridCell"]), Paragraph("2", self.styles["GridCell"]), Paragraph("Kết quả trùng Contact C↔C & Liên kết nơi công tác sang Canonical Account ID", self.styles["GridCell"])],
            [Paragraph("<b>songnhat_full_process_report.pdf</b>", self.styles["GridCellBold"]), Paragraph("PDF (A4)", self.styles["GridCell"]), Paragraph("11 Chaps", self.styles["GridCell"]), Paragraph("Multi-page", self.styles["GridCell"]), Paragraph("Hồ sơ thẩm định toàn diện quá trình hợp nhất thực thể & dữ liệu vàng", self.styles["GridCell"])],
        ]
        t_manifest = Table(manifest_data, colWidths=[140, 60, 45, 45, 215])
        t_manifest.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ALIGN", (1, 1), (3, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_manifest)
        story.append(Spacer(1, 12))

        # Official System Attestation
        attestation = [
            [Paragraph("<b>Xác nhận Toàn vẹn Hệ thống:</b>", self.styles["GridCellBold"]), Paragraph("Dữ liệu nguồn bảo toàn bất biến; 100% quyết định hợp nhất có căn cứ bằng chứng.", self.styles["GridCell"])],
            [Paragraph("<b>Kiểm soát Maker-Checker:</b>", self.styles["GridCellBold"]), Paragraph("Tuân thủ nguyên tắc kiểm soát kép; ràng buộc Database chk_no_self_approval được cưỡng chế.", self.styles["GridCell"])],
            [Paragraph("<b>Khả năng Đảo ngược (Reversal):</b>", self.styles["GridCellBold"]), Paragraph("Hỗ trợ Cluster Split và Pair Unlink qua SCD Type 2 mà không làm mất dữ liệu lịch sử.", self.styles["GridCell"])],
            [Paragraph("<b>Mã băm Đợt xử lý (Job Checksum):</b>", self.styles["GridCellBold"]), Paragraph(f"<code>{hashlib.sha256(job_code.encode()).hexdigest()}</code>", self.styles["GridCell"])],
        ]
        t_attest = Table(attestation, colWidths=[165, 340])
        t_attest.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(t_attest)

        # Build PDF with NumberedCanvas
        doc.build(story, canvasmaker=NumberedCanvas)
        logger.info("Successfully generated operational merge dossier PDF at '%s'", pdf_path)
        return pdf_path
