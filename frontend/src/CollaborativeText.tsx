import { Collaboration } from "@tiptap/extension-collaboration";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import * as Y from "yjs";

const MAX_HREF = 2048;

function safeHref(value: string): string | null {
  const candidate = value.trim();
  if (!candidate || candidate.length > MAX_HREF || /[\u0000-\u001F\u007F\s]/.test(candidate)) return null;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }
  if (url.username || url.password) return null;
  if (url.protocol === "http:" || url.protocol === "https:") {
    if (!url.hostname) return null;
    return url.href;
  }
  if (url.protocol === "mailto:") {
    if (!url.pathname || /[<>]/.test(url.pathname)) return null;
    return `mailto:${url.pathname}${url.search}`;
  }
  return null;
}

function normalizeHref(value: string): string | null {
  const trimmed = value.trim();
  return safeHref(trimmed) ?? safeHref(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
}

function pastedHtml(html: string): string {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  parsed
    .querySelectorAll(
      "script, style, iframe, object, embed, img, picture, source, link, meta, form, svg, math, video, audio, canvas, noscript, template, base, applet, frame, frameset, input, button, textarea, select, option",
    )
    .forEach((node) => node.remove());
  parsed.querySelectorAll("*").forEach((node) => {
    for (const attr of [...node.attributes]) {
      if (attr.name.toLowerCase() !== "href") {
        node.removeAttribute(attr.name);
        continue;
      }
      const safe = safeHref(attr.value);
      if (!safe) node.removeAttribute(attr.name);
      else node.setAttribute(attr.name, safe);
    }
  });
  return parsed.body.innerHTML;
}

function ToolButton({
  label,
  pressed = false,
  disabled,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={pressed ? "desk-tool on" : "desk-tool"}
      aria-pressed={pressed}
      aria-label={label}
      title={label}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function editorSnapshot(editor: Editor) {
  const href = editor.getAttributes("link").href;
  const text = editor.getText().trim();
  return {
    bold: editor.isActive("bold"),
    italic: editor.isActive("italic"),
    underline: editor.isActive("underline"),
    strike: editor.isActive("strike"),
    code: editor.isActive("code"),
    h1: editor.isActive("heading", { level: 1 }),
    h2: editor.isActive("heading", { level: 2 }),
    h3: editor.isActive("heading", { level: 3 }),
    bullet: editor.isActive("bulletList"),
    ordered: editor.isActive("orderedList"),
    quote: editor.isActive("blockquote"),
    codeBlock: editor.isActive("codeBlock"),
    link: editor.isActive("link"),
    href: typeof href === "string" ? href : "",
    canUndo: editor.can().undo(),
    canRedo: editor.can().redo(),
    empty: editor.isEmpty,
    words: text ? text.split(/\s+/).length : 0,
  };
}

export function CollaborativeText({
  doc,
  canEdit,
  history,
  below,
  onHistory,
}: {
  doc: Y.Doc;
  canEdit: boolean;
  history?: ReactNode;
  below?: ReactNode;
  onHistory?: () => void;
}) {
  const linkFieldId = useId();
  const linkInput = useRef<HTMLInputElement>(null);
  const canEditRef = useRef(canEdit);
  canEditRef.current = canEdit;
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkDraft, setLinkDraft] = useState("");
  const [linkError, setLinkError] = useState("");

  const editor = useEditor(
    {
      editable: canEdit,
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2, 3] },
          link: {
            openOnClick: false,
            autolink: true,
            linkOnPaste: true,
            defaultProtocol: "https",
            HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" },
            isAllowedUri: (url) => safeHref(url) !== null,
            shouldAutoLink: (url) => normalizeHref(url) !== null,
          },
          undoRedo: false,
        }),
        Collaboration.configure({ document: doc, field: "content" }),
      ],
      editorProps: {
        attributes: {
          class: "doc",
          "aria-label": "Document text",
          spellcheck: "true",
        },
        transformPastedHTML: pastedHtml,
        handlePaste: (_view, event) => {
          const data = event.clipboardData;
          if (!data || data.files.length === 0) return false;
          if (data.getData("text/html") || data.getData("text/plain")) return false;
          event.preventDefault();
          return true;
        },
        handleDrop: (_view, event) => {
          if (!event.dataTransfer?.files.length) return false;
          event.preventDefault();
          return true;
        },
        handleClick: (_view, _pos, event) => {
          if (canEditRef.current) return false;
          const target = event.target;
          if (!(target instanceof Element)) return false;
          const anchor = target.closest("a");
          const href = anchor?.getAttribute("href");
          if (!anchor || !href) return false;
          const safe = safeHref(href);
          event.preventDefault();
          if (safe) window.open(safe, "_blank", "noopener,noreferrer");
          return true;
        },
      },
    },
    [doc],
  );

  const state = useEditorState({
    editor,
    selector: ({ editor: current }) => editorSnapshot(current),
  });

  useEffect(() => {
    editor.setEditable(canEdit);
    if (!canEdit) setLinkOpen(false);
  }, [editor, canEdit]);

  useEffect(() => {
    if (linkOpen) linkInput.current?.focus();
  }, [linkOpen]);

  function run(action: (current: Editor) => void) {
    if (!canEdit) return;
    action(editor);
  }

  function applyBlock(value: string) {
    run((current) => {
      const chain = current.chain().focus();
      if (value === "1" || value === "2" || value === "3") {
        chain.setHeading({ level: Number(value) as 1 | 2 | 3 }).run();
        return;
      }
      chain.setParagraph().run();
    });
  }

  function applyLink() {
    const safe = normalizeHref(linkDraft);
    if (!safe) {
      setLinkError("Use an https, http, or mailto address");
      return;
    }
    run((current) => {
      const { from, to } = current.state.selection;
      const chain = current.chain().focus().extendMarkRange("link");
      if (from === to && !current.isActive("link")) {
        chain
          .insertContent({
            type: "text",
            text: safe,
            marks: [{ type: "link", attrs: { href: safe } }],
          })
          .run();
        return;
      }
      chain.setLink({ href: safe }).run();
    });
    setLinkError("");
    setLinkOpen(false);
  }

  const disabled = !canEdit;

  return (
    <>
      <div className="desk-tools">
        <div className="desk-tools-scroll" role="toolbar" aria-label="Formatting">
          <ToolButton label="Heading" pressed={state.h1} disabled={disabled} onClick={() => applyBlock(state.h1 ? "p" : "1")}>
            Heading
          </ToolButton>
          <ToolButton label="Subheading" pressed={state.h2} disabled={disabled} onClick={() => applyBlock(state.h2 ? "p" : "2")}>
            Subheading
          </ToolButton>
          <span className="desk-rule" />
          <ToolButton label="Bold" pressed={state.bold} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleBold().run())}>
            <b>B</b>
          </ToolButton>
          <ToolButton label="Italic" pressed={state.italic} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleItalic().run())}>
            <i>I</i>
          </ToolButton>
          <ToolButton label="Underline" pressed={state.underline} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleUnderline().run())}>
            <u>U</u>
          </ToolButton>
          <ToolButton label="Inline code" pressed={state.code || state.codeBlock} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleCode().run())}>
            {"</>"}
          </ToolButton>
          <ToolButton label="Bulleted list" pressed={state.bullet} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleBulletList().run())}>
            List
          </ToolButton>
          <ToolButton label="Numbered list" pressed={state.ordered} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleOrderedList().run())}>
            1.
          </ToolButton>
          <ToolButton label="Quote" pressed={state.quote} disabled={disabled} onClick={() => run((current) => current.chain().focus().toggleBlockquote().run())}>
            Quote
          </ToolButton>
          <ToolButton label="Divider" disabled={disabled} onClick={() => run((current) => current.chain().focus().setHorizontalRule().run())}>
            Rule
          </ToolButton>
          <span className="desk-rule" />
          <ToolButton
            label="Link"
            pressed={state.link || linkOpen}
            disabled={disabled}
            onClick={() => {
              setLinkDraft(state.href);
              setLinkError("");
              setLinkOpen((open) => !open);
            }}
          >
            Link
          </ToolButton>
          <ToolButton label="Clear formatting" disabled={disabled} onClick={() => run((current) => current.chain().focus().unsetAllMarks().clearNodes().run())}>
            Clear
          </ToolButton>
          <ToolButton label="Undo" disabled={disabled || !state.canUndo} onClick={() => run((current) => current.chain().focus().undo().run())}>
            Undo
          </ToolButton>
          <ToolButton label="Redo" disabled={disabled || !state.canRedo} onClick={() => run((current) => current.chain().focus().redo().run())}>
            Redo
          </ToolButton>
        </div>
        {onHistory ? (
          <button type="button" className={history ? "desk-history-button on" : "desk-history-button"} onClick={onHistory}>
            Version history
          </button>
        ) : null}
      </div>
      {linkOpen ? (
        <form
          className="desk-link"
          onSubmit={(event) => {
            event.preventDefault();
            applyLink();
          }}
        >
          <label htmlFor={linkFieldId}>Address</label>
          <input
            id={linkFieldId}
            ref={linkInput}
            value={linkDraft}
            maxLength={MAX_HREF}
            autoComplete="off"
            spellCheck={false}
            placeholder="https://example.com"
            onChange={(event) => {
              setLinkDraft(event.target.value);
              setLinkError("");
            }}
          />
          <button type="submit" className="desk-primary" disabled={disabled}>
            Apply
          </button>
          <button
            type="button"
            className="desk-secondary"
            disabled={disabled || !state.link}
            onClick={() => {
              run((current) => current.chain().focus().extendMarkRange("link").unsetLink().run());
              setLinkOpen(false);
              setLinkError("");
            }}
          >
            Remove
          </button>
          {linkError ? <p className="desk-error">{linkError}</p> : null}
        </form>
      ) : null}
      <main className="desk-canvas">
        <div className={history ? "desk-stage with-history" : "desk-stage"}>
          <article className={state.empty ? "desk-sheet is-empty" : "desk-sheet"}>
            <EditorContent editor={editor} />
          </article>
          {history}
        </div>
        {below}
      </main>
    </>
  );
}
