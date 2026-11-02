---- MODULE TaskLifecycle ----
EXTENDS Naturals

CONSTANT MaxWip
ASSUME MaxWip > 0

VARIABLES status, gate, control, merged, workerDone, active, worktrees

vars == <<status, gate, control, merged, workerDone, active, worktrees>>

Init ==
    /\ status = "queued"
    /\ gate = FALSE
    /\ control = FALSE
    /\ merged = FALSE
    /\ workerDone = FALSE
    /\ active = 0
    /\ worktrees = 0

Claim ==
    /\ status = "queued"
    /\ active < MaxWip
    /\ status' = "claimed"
    /\ active' = active + 1
    /\ UNCHANGED <<gate, control, merged, workerDone, worktrees>>

Start ==
    /\ status = "claimed"
    /\ status' = "working"
    /\ worktrees' = worktrees + 1
    /\ UNCHANGED <<gate, control, merged, workerDone, active>>

Block ==
    /\ status = "working"
    /\ status' = "blocked"
    /\ UNCHANGED <<gate, control, merged, workerDone, active, worktrees>>

Answer ==
    /\ status = "blocked"
    /\ status' = "working"
    /\ UNCHANGED <<gate, control, merged, workerDone, active, worktrees>>

WorkerDone ==
    /\ status = "working"
    /\ status' = "ready"
    /\ workerDone' = TRUE
    /\ UNCHANGED <<gate, control, merged, active, worktrees>>

GatePass ==
    /\ status = "ready"
    /\ workerDone
    /\ status' = "gated"
    /\ gate' = TRUE
    /\ control' = TRUE
    /\ UNCHANGED <<merged, workerDone, active, worktrees>>

GateFail ==
    /\ status = "ready"
    /\ workerDone
    /\ active > 0
    /\ worktrees > 0
    /\ status' = "queued"
    /\ active' = active - 1
    /\ worktrees' = worktrees - 1
    /\ UNCHANGED <<gate, control, merged, workerDone>>

Merge ==
    /\ status = "gated"
    /\ gate
    /\ control
    /\ workerDone
    /\ active > 0
    /\ worktrees > 0
    /\ status' = "done"
    /\ merged' = TRUE
    /\ active' = active - 1
    /\ worktrees' = worktrees - 1
    /\ UNCHANGED <<gate, control, workerDone>>

Next == Claim \/ Start \/ Block \/ Answer \/ WorkerDone \/ GatePass \/ GateFail \/ Merge

Spec == Init /\ [][Next]_vars

DoneHasGate == (status = "done") => (gate /\ control)
MergedHasGate == merged => (gate /\ control)
WipBound == active <= MaxWip
NoNegative == active >= 0 /\ worktrees >= 0
DoneAfterWorker == (status = "done") => workerDone

====
