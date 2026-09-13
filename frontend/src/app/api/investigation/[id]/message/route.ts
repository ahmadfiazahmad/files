import { NextResponse } from "next/server";

import type { ChatAttachment, DegreeLevel, FundingType } from "@/types";
import { runInvestigationTurn } from "@/server/engine/run";
import { backendEnabled, backendContinueInvestigation } from "@/server/backendClient";
import { adaptAssistantMessage, adaptContext } from "@/server/backendAdapter";
import { getStudentKey } from "@/server/session";
import { ensureExternalInvestigation, appendMessage, syncExternalInvestigation } from "@/server/repositories/investigations";

export const dynamic = "force-dynamic";

interface MessageBody {
  message?: string;
  attachments?: ChatAttachment[];
  degree_level?: DegreeLevel | null;
  funding_type?: FundingType | null;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const body = (await request.json().catch(() => ({}))) as MessageBody;
    const text = (body.message ?? "").trim();
    const attachments = body.attachments ?? [];
    if (!text && attachments.length === 0) {
      return NextResponse.json({ error: "Message or evidence is required" }, { status: 400 });
    }

    // Backend investigation ids are opaque strings (see database/models.py),
    // not the numeric ids the internal engine uses — do not coerce with Number().
    if (backendEnabled()) {
      const backendResult = await backendContinueInvestigation(id, text);
      const assistantMessage = adaptAssistantMessage(backendResult.assistant_message, null);
      const studentKey = await getStudentKey();
      const mirror = await ensureExternalInvestigation({ studentKey, externalId: id, context: adaptContext(backendResult.structured_case) });
      await appendMessage({ investigationId: mirror.id, role: "student", text });
      await appendMessage({ investigationId: mirror.id, role: "assistant", text: backendResult.assistant_message });
      await syncExternalInvestigation({ externalId: id, studentKey, context: adaptContext(backendResult.structured_case), status: backendResult.ready_for_verification ? "ready_for_verification" : "in_progress" });
      return NextResponse.json({
        assistantMessage,
        result: null,
        mode: "external_backend",
      });
    }

    const investigationId = Number(id);
    if (!Number.isFinite(investigationId)) {
      return NextResponse.json({ error: "Invalid investigation id" }, { status: 400 });
    }

    const turn = await runInvestigationTurn({
      investigationId,
      studentText: text,
      attachments,
      explicitDegree: body.degree_level ?? null,
      explicitFunding: body.funding_type ?? null,
    });

    return NextResponse.json({ ...turn, mode: "internal_engine" });
  } catch (error) {
    console.error("message turn failed", error);
    return NextResponse.json({ error: "Failed to process the message" }, { status: 500 });
  }
}
