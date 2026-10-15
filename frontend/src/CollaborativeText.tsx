import { Collaboration } from "@tiptap/extension-collaboration";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";
import * as Y from "yjs";

function pastedHtml(html: string): string {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  parsed.querySelectorAll("script, style, iframe, object, embed, img, link, meta, form").forEach((node) => node.remove());
  return parsed.body.innerHTML;
}

export function CollaborativeText({ doc, canEdit }: { doc: Y.Doc; canEdit: boolean }) {
  const editor = useEditor(
    {
      editable: canEdit,
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2] },
          blockquote: false,
          bold: {},
          bulletList: false,
          code: false,
          codeBlock: false,
          dropcursor: false,
          horizontalRule: false,
          italic: {},
          link: false,
          listItem: false,
          listKeymap: false,
          orderedList: false,
          strike: false,
          underline: false,
          undoRedo: false,
        }),
        Collaboration.configure({ document: doc, field: "content" }),
      ],
      editorProps: {
        attributes: { class: "doc", "aria-label": "Document text" },
        transformPastedHTML: pastedHtml,
      },
    },
    [doc],
  );

  useEffect(() => {
    editor?.setEditable(canEdit);
  }, [editor, canEdit]);

  return (
    <div className="doc-editor">
      <div className="toolbar">
        <button type="button" disabled={!canEdit || !editor} onClick={() => editor?.chain().focus().toggleBold().run()}>
          Bold
        </button>
        <button type="button" disabled={!canEdit || !editor} onClick={() => editor?.chain().focus().toggleItalic().run()}>
          Italic
        </button>
        <button
          type="button"
          disabled={!canEdit || !editor}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
        >
          Heading
        </button>
        <button
          type="button"
          disabled={!canEdit || !editor}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
        >
          Subheading
        </button>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
