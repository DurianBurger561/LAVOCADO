"""Bounded address-bar search must not inspect web-page edit fields."""

import unittest
from dataclasses import dataclass, field

from app.context.website.accessibility import TraversalLimitExceeded, find_address_hostname


@dataclass
class Node:
    role: str = "other"
    identifier: str | None = None
    name: str | None = None
    value: str | None = None
    children: list["Node"] = field(default_factory=list)


class FakeTree:
    def __init__(self) -> None:
        self.values_read = 0
        self.child_calls = 0

    def role(self, node):
        return node.role

    def identifier(self, node):
        return node.identifier

    def name(self, node):
        return node.name

    def value(self, node):
        self.values_read += 1
        return node.value

    def children(self, node, limit):
        self.child_calls += 1
        if len(node.children) > limit:
            raise TraversalLimitExceeded()
        return node.children[:limit]


class WebsiteAccessibilityTests(unittest.TestCase):
    def test_only_explicit_address_bar_is_read(self) -> None:
        tree = FakeTree()
        root = Node(children=[
            Node(role="edit", name="Search", value="https://wrong.example/"),
            Node(role="edit", identifier="urlbar-input", value="https://site.example/private?q=secret"),
            Node(role="document", children=[
                Node(role="edit", name="Address bar", value="https://evil.example/")
            ]),
        ])

        self.assertEqual(find_address_hostname(root, tree), "site.example")
        self.assertEqual(tree.values_read, 1)
        self.assertEqual(tree.child_calls, 1)

    def test_ambiguous_address_controls_are_unknown(self) -> None:
        root = Node(children=[
            Node(role="edit", name="Address bar", value="https://one.example/"),
            Node(role="edit", name="Location bar", value="https://two.example/"),
        ])
        self.assertIsNone(find_address_hostname(root, FakeTree()))

    def test_unlabelled_edit_and_invalid_value_are_unknown(self) -> None:
        root = Node(children=[
            Node(role="edit", value="https://private.example/"),
            Node(role="edit", name="Address bar", value="about:blank"),
        ])
        self.assertIsNone(find_address_hostname(root, FakeTree()))

    def test_search_respects_node_and_depth_limits(self) -> None:
        hidden = Node(role="edit", name="Address bar", value="https://too-deep.example/")
        root = Node(children=[Node(children=[Node(children=[hidden])])])
        self.assertIsNone(find_address_hostname(root, FakeTree(), max_depth=2))
        self.assertIsNone(find_address_hostname(root, FakeTree(), max_nodes=2))

    def test_partial_tree_never_triggers_website_whitelist(self) -> None:
        root = Node(children=[
            Node(role="edit", name="Address bar", value="https://trusted.example/"),
            Node(children=[Node(role="edit", name="Address bar", value="https://blocked.example/")]),
        ])
        self.assertIsNone(find_address_hostname(root, FakeTree(), max_nodes=2))
        self.assertIsNone(find_address_hostname(root, FakeTree(), max_children=1))


if __name__ == "__main__":
    unittest.main()
