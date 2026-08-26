import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AsyncList } from "../AsyncList";

interface Item {
  id: string;
  label: string;
}

const items: Item[] = [
  { id: "a", label: "Alpha" },
  { id: "b", label: "Beta" },
];

describe("AsyncList", () => {
  it("renders the loading text while loading", () => {
    render(
      <AsyncList<Item>
        isLoading
        items={undefined}
        renderItem={() => null}
        emptyText="Nothing here"
      />,
    );

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
  });

  it("renders a custom loading text when provided", () => {
    render(
      <AsyncList<Item>
        isLoading
        items={undefined}
        renderItem={() => null}
        emptyText="Nothing here"
        loadingText="Fetching..."
      />,
    );

    expect(screen.getByText("Fetching...")).toBeInTheDocument();
  });

  it("renders the empty text when there are no items", () => {
    render(
      <AsyncList<Item>
        isLoading={false}
        items={[]}
        renderItem={() => null}
        emptyText="No items yet."
      />,
    );

    expect(screen.getByText("No items yet.")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  });

  it("renders the empty text when items is undefined and not loading", () => {
    render(
      <AsyncList<Item>
        isLoading={false}
        items={undefined}
        renderItem={() => null}
        emptyText="No items yet."
      />,
    );

    expect(screen.getByText("No items yet.")).toBeInTheDocument();
  });

  it("renders every item via renderItem", () => {
    render(
      <AsyncList<Item>
        isLoading={false}
        items={items}
        emptyText="No items yet."
        renderItem={(item) => <div key={item.id}>{item.label}</div>}
      />,
    );

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.queryByText("No items yet.")).not.toBeInTheDocument();
  });

  it("renders items inside a wrapper container when listStyle is provided", () => {
    const { container } = render(
      <AsyncList<Item>
        isLoading={false}
        items={items}
        emptyText="No items yet."
        listStyle={{ display: "grid", gap: 8 }}
        renderItem={(item) => <div key={item.id}>{item.label}</div>}
      />,
    );

    // The list container (a plain <div>) is the direct parent of each rendered item.
    const alphaBlock = screen.getByText("Alpha").closest("div");
    expect(alphaBlock).not.toBeNull();
    expect(alphaBlock?.parentElement).toBe(container.firstElementChild);
    expect(container.firstElementChild).not.toBeNull();
  });

  it("exposes clickable items rendered by renderItem to the user", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <AsyncList<Item>
        isLoading={false}
        items={items}
        emptyText="No items yet."
        renderItem={(item) => (
          <button key={item.id} type="button" onClick={() => onSelect(item.id)}>
            {item.label}
          </button>
        )}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Beta" }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("b");
  });
});
