import { NextResponse } from "next/server";

import type { ChatAttachment, DegreeLevel, FundingType, InvestigationRecord, Language } from "@/types";
import { startNewInvestigation } from "@/server/engine/run";
import { getStudentKey } from "@/server/session";
import { getInvestigation, ensureExternalInvestigation, appendMessage, syncExternalInvestigation } from "@/server/repositories/investigations";
import { backendEnabled, backendCreateInvestigation, backendGetResults, backendRunVerification } from "@/server/backendClient";
import { adaptAssistantMessage, adaptContext, adaptStudentMessage, adaptReport } from "@/server/backendAdapter";

export const dynamic = "force-dynamic";

interface StartBody {
  message?: string;
  language?: Language;
  degree_level?: DegreeLevel;
  funding_type?: FundingType;
  attachments?: ChatAttachment[];
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as StartBody;
    const language: Language = body.language ?? "roman_urdu";
    const message = body.message ?? "";

    // When BACKEND_URL is configured, the FastAPI service owns the investigation
    // (see backend/api/investigation.py: POST /investigations). Otherwise this
    // falls through, unchanged, to the internal deterministic engine below.
    if (backendEnabled()) {
      const created = await backendCreateInvestigation(message || "I need help verifying a study abroad offer.");
      const studentKey = await getStudentKey();
      let mirror: Awaited<ReturnType<typeof ensureExternalInvestigation>> = null;
      try {
        mirror = await ensureExternalInvestigation({
          studentKey,
          externalId: created.investigation_id,
          title: created.structured_case.university || message.slice(0, 80) || "New investigation",
          language,
          context: adaptContext(created.structured_case),
        });
      } catch (mirrorError) {
        console.warn("Frontend mirror unavailable; continuing with FastAPI backend", mirrorError);
      }
      const studentMessage = adaptStudentMessage(message || "I need help verifying a study abroad offer.");
      let reportResult = null;
      if (created.ready_for_verification) {
        try {
          await backendRunVerification(created.investigation_id);
          const reportData = await backendGetResults(created.investigation_id);
          if (reportData.report) {
            reportResult = adaptReport(created.investigation_id, language, reportData.report, reportData.display_status);
          }
        } catch (verificationError) {
          console.warn("Automatic verification did not complete", verificationError);
        }
      }
      const assistantMessage = adaptAssistantMessage(created.assistant_message, reportResult);
      const now = new Date().toISOString();
      const investigation: InvestigationRecord = {
        id: created.investigation_id,
        title: created.structured_case.university || message.slice(0, 80) || "New investigation",
        language,
        status: created.ready_for_verification ? "assessed" : "gathering",
        overall_risk: "pending_more_info",
        context: adaptContext(created.structured_case),
        messages: [studentMessage, assistantMessage],
        latest_result: reportResult,
        created_at: now,
        updated_at: now,
      };
      if (mirror) {
        await appendMessage({ investigationId: mirror.id, role: "student", text: message || "I need help verifying a study abroad offer." });
        await appendMessage({ investigationId: mirror.id, role: "assistant", text: created.assistant_message });
        await syncExternalInvestigation({
          externalId: created.investigation_id,
          studentKey,
          context: adaptContext(created.structured_case),
          status: created.ready_for_verification ? "ready_for_verification" : "in_progress",
        });
      }
      return NextResponse.json({
        investigation_id: created.investigation_id,
        investigation,
        first_turn: { assistantMessage, result: reportResult },
        mode: "external_backend",
      });
    }

    const studentKey = await getStudentKey();
    const started = await startNewInvestigation({
      studentKey,
      language,
      firstMessage: message,
      attachments: body.attachments ?? [],
    });

    const investigation = await getInvestigation(started.investigationId);

    return NextResponse.json({
      investigation_id: String(started.investigationId),
      investigation,
      first_turn: started.turn,
      mode: "internal_engine",
    });
  } catch (error) {
    console.error("investigate failed", error);
    return NextResponse.json({ error: "Failed to start investigation" }, { status: 500 });
  }
}
