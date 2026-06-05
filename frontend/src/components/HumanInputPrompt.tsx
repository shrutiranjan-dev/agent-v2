import { Check, MessageCircleQuestion, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { HumanInputRequest } from "../api/client";

type HumanInputPromptProps = {
  request: HumanInputRequest;
  busy?: "answer" | "cancel";
  compact?: boolean;
  onAnswer: (id: string, answer: string) => void;
  onCancel: (id: string) => void;
};

export function HumanInputPrompt(props: HumanInputPromptProps) {
  const choices = props.request.choices ?? [];
  const [answer, setAnswer] = useState(choices[0] ?? "");
  const canSubmit = useMemo(() => {
    const trimmed = answer.trim();
    if (!trimmed) return false;
    if (choices.length && !props.request.allow_free_text) return choices.includes(trimmed);
    return true;
  }, [answer, choices, props.request.allow_free_text]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || props.busy) return;
    props.onAnswer(props.request.id, answer.trim());
  }

  return (
    <article className={props.compact ? "chat-permission human-input-card" : "human-input-card"}>
      <header>
        <MessageCircleQuestion size={18} />
        <div>
          <strong>Human input needed</strong>
          <span>{props.request.status} · run {props.request.agent_run_id}</span>
        </div>
      </header>
      <p>{props.request.question}</p>
      {props.request.expires_at && <span className="prompt-expiry">Expires {new Date(props.request.expires_at).toLocaleString()}</span>}
      <form onSubmit={submit}>
        {choices.length > 0 && (
          <div className="choice-row">
            {choices.map((choice) => (
              <button
                key={choice}
                type="button"
                className={answer === choice ? "selected" : ""}
                disabled={Boolean(props.busy)}
                onClick={() => setAnswer(choice)}
              >
                {choice}
              </button>
            ))}
          </div>
        )}
        {props.request.allow_free_text && (
          <textarea
            value={answer}
            disabled={Boolean(props.busy)}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="Type your answer"
          />
        )}
        <footer>
          <button type="submit" disabled={!canSubmit || Boolean(props.busy)}>
            <Check size={15} />
            {props.busy === "answer" ? "Answering" : "Answer"}
          </button>
          <button type="button" className="danger" disabled={Boolean(props.busy)} onClick={() => props.onCancel(props.request.id)}>
            <X size={15} />
            {props.busy === "cancel" ? "Cancelling" : "Cancel"}
          </button>
        </footer>
      </form>
    </article>
  );
}
