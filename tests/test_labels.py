"""Step 27: owner corrections as labels, agreement, and the rule gate. Every label is a regression test
(its read must stay what the last report recorded); pins catch edited evidence; conflicting sources stop the
build; a skip counts only with a stated no-side reason; rules are kept only through the gate and applied only
while bound to their code and the current labels; nothing here changes a score. Run: python3 -m unittest -v tests.test_labels"""
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import labels as lb  # noqa: E402
import reader  # noqa: E402

LABELS = json.load(open(os.path.join(HERE, "data", "labels.json")))["labels"]
REPORT = json.load(open(os.path.join(HERE, "web", "data", "agreement.json")))
KEPT = reader.kept_rules()
NEST = "More $NEST and $KNTQ"


class EveryLabelIsARegressionTest(unittest.TestCase):
    def test_each_label_reads_as_the_report_recorded_and_no_agreed_label_breaks(self):
        rows = {r["id"]: r for r in REPORT["rows"]}
        self.assertEqual(len(rows), len(LABELS))
        for l in LABELS:
            with self.subTest(label=l["id"]):
                now = lb.read_label(l, KEPT)
                self.assertEqual(now["side"], rows[l["id"]]["read_now"]["side"])
                if l["gating"] and rows[l["id"]]["agree_now"]:
                    self.assertTrue(lb.agrees(l, now))

    def test_each_label_still_hashes_to_its_pin(self):
        for l in LABELS:
            with self.subTest(label=l["id"]):
                self.assertEqual(lb.sha(lb.pin_view(l)), l["pinned_sha256"])

    def test_the_reads_owners_accepted_as_read_are_what_the_base_reader_gives(self):
        for l in (x for x in LABELS if x["owner"]["method"] == "as read"):
            with self.subTest(label=l["id"]):
                self.assertEqual(lb.read_label(l, [])["side"], l["owner"]["side"])

    def test_the_rebuild_is_stable(self):
        root = tempfile.mkdtemp(prefix="quanty-labels-")
        try:
            for d in ("records", "intake", "data"):
                shutil.copytree(os.path.join(HERE, d), os.path.join(root, d))
            copy_cards = {"cards": {}}
            p = os.path.join(root, "cards.json")
            json.dump(copy_cards, open(p, "w"))
            labels, new = lb.build(root, cards_path=p, watch_dir=root)       # the watcher's state is not here: its labels stay pinned as they are
            self.assertEqual(new, [])
            self.assertEqual(len(labels), len(LABELS))
        finally:
            shutil.rmtree(root)


class TheRealCorrections(unittest.TestCase):
    def label(self, lid):
        return next(l for l in LABELS if l["id"] == lid)

    def test_nest_and_kntq(self):
        for asset in ("NEST", "KNTQ"):
            l = self.label(f"2118181656398090718|{asset}")
            self.assertEqual((l["kind"], l["first_read"]["side"], l["owner"]["side"], l["owner"]["method"]), ("side_added", "none", "long", "changed"))
            self.assertEqual(sorted(s["type"] for s in l["sources"]), ["record", "watcher"])
            self.assertEqual(lb.read_label(l, [])["side"], "none")                   # the base reader missed it
            r = lb.read_label(l, KEPT)
            self.assertEqual((r["side"], r["rule"]), ("long", "more_cashtag"))        # the learned rule reads it
        self.assertEqual(reader.read(NEST, ["NEST"], multi=True)["side"], 1)
        self.assertIsNone(reader.read(NEST, ["NEST"], multi=True, rules=[])["side"])

    def test_the_gate_kept_and_rejected(self):
        g = {x["rule"]: x for x in json.load(open(os.path.join(HERE, "data", "rules.json")))["gate"]}
        self.assertEqual(g["more_cashtag"]["decision"], "kept")
        self.assertEqual(g["more_cashtag"]["fixed"], ["2118181656398090718|KNTQ", "2118181656398090718|NEST"])
        self.assertEqual(g["bullish_anywhere"]["decision"], "rejected")
        self.assertEqual(g["bullish_anywhere"]["worsened"], ["2091161059801391206|-"])           # "'bullish nonetheless' ... hedged"
        for x in g.values():
            self.assertTrue(x["decision"] == "rejected" or (x["after"]["agree"] > x["before"]["agree"] and not x["worsened"]), x["rule"])

    def test_skips_count_only_with_a_stated_no_side_reason(self):
        self.assertTrue(self.label("2005330899899121670|-")["gating"])                     # "'very mixed feeling on Bitcoin': no side"
        self.assertFalse(self.label("1985730433510973908|-")["gating"])                    # "... a repeat"
        self.assertFalse(self.label("2118672055420039460|-")["gating"])                    # a watcher Skip without a reason
        self.assertEqual(self.label("2009291616217903397|-")["kind"], "false_call")        # 'still bullish' inside a quoted AI answer


class Gate(unittest.TestCase):
    def labels(self):
        def L(i, text, owner_side, decision="add"):
            return {"id": f"{i}|X", "post": {"text": text}, "aliases": ["X"], "multi": False, "gating": True,
                    "owner": {"decision": decision, "side": owner_side}, "pinned_sha256": str(i)}
        return [L(1, "more $X please", "long"), L(2, "I want more $X? no, too risky: no position", "none"),
                L(3, "picking up 5 X here", "long")]

    def run_gate(self, labels, order):
        root = tempfile.mkdtemp(prefix="quanty-gate-")
        try:
            os.makedirs(os.path.join(root, "data"))
            json.dump({"labels": labels}, open(os.path.join(root, "data", "labels.json"), "w"))
            real = reader.ORDER
            reader.ORDER = order
            try:
                return lb.gate(root)
            finally:
                reader.ORDER = real
        finally:
            shutil.rmtree(root)

    def test_a_rule_that_breaks_an_agreed_label_is_rejected_even_if_it_fixes_another(self):
        d = self.run_gate(self.labels(), ["more_cashtag"])
        g = d["gate"][0]
        self.assertEqual((g["decision"], g["fixed"], g["worsened"]), ("rejected", ["1|X"], ["2|X"]))
        self.assertEqual(d["kept"], [])

    def test_a_rule_that_only_fixes_is_kept_and_bound(self):
        d = self.run_gate(self.labels(), ["picking_up_quantity"])
        self.assertEqual(d["kept"], ["picking_up_quantity"])
        self.assertEqual(d["bindings"]["picking_up_quantity"]["code_sha256"], lb.code_sha("picking_up_quantity"))

    def test_a_rule_that_changes_nothing_is_rejected(self):
        self.assertEqual(self.run_gate(self.labels()[:2], ["targeting_price"])["gate"][0]["why"], "agreement does not rise")


class Binding(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-bind-")
        os.makedirs(os.path.join(self.root, "data"))
        shutil.copy(os.path.join(HERE, "data", "labels.json"), os.path.join(self.root, "data", "labels.json"))
        shutil.copy(os.path.join(HERE, "data", "rules.json"), os.path.join(self.root, "data", "rules.json"))
        self.rp, self.lp = os.path.join(self.root, "data", "rules.json"), os.path.join(self.root, "data", "labels.json")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_bound_rules_apply(self):
        self.assertIn("more_cashtag", reader.kept_rules(self.rp, self.lp))

    def test_edited_code_is_not_applied(self):
        d = json.load(open(self.rp))
        d["bindings"]["more_cashtag"]["code_sha256"] = "0" * 64
        json.dump(d, open(self.rp, "w"))
        self.assertNotIn("more_cashtag", reader.kept_rules(self.rp, self.lp))

    def test_new_labels_switch_rules_off_until_verified_and_a_breaking_label_drops_the_rule(self):
        d = json.load(open(self.lp))
        new = copy.deepcopy(next(l for l in d["labels"] if l["id"] == "2118181656398090718|NEST"))
        new.update(id="9|NEST", gating=True, owner={**new["owner"], "side": "none"})          # an owner who says "More $NEST" is not a call
        new["pinned_sha256"] = lb.sha(lb.pin_view(new))
        d["labels"].append(new)
        json.dump(d, open(self.lp, "w"))
        self.assertEqual(reader.kept_rules(self.rp, self.lp), [])                            # not verified on these labels: off
        dropped = lb.verify_kept(self.root)
        self.assertIn("more_cashtag", [x["rule"] for x in dropped])
        self.assertNotIn("more_cashtag", reader.kept_rules(self.rp, self.lp))
        self.assertIn("positioned_side", reader.kept_rules(self.rp, self.lp))              # the others re-verified


class Provenance(unittest.TestCase):
    def scratch(self):
        root = tempfile.mkdtemp(prefix="quanty-prov-")
        for d in ("records", "intake", "data"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(root, d))
        p = os.path.join(root, "cards.json")
        json.dump({"cards": {}}, open(p, "w"))
        return root, p

    def test_an_edited_source_stops_the_build_and_writes_nothing(self):
        root, cards = self.scratch()
        try:
            f = next(x for x in glob.glob(os.path.join(root, "records", "**", "*_NEST.json"), recursive=True))
            r = json.load(open(f))
            r["side_choice"]["reason"] = "rewritten later"
            json.dump(r, open(f, "w"))
            before = open(os.path.join(root, "data", "labels.json"), "rb").read()
            with self.assertRaises(lb.Conflict):
                lb.build(root, cards_path=cards, watch_dir=root)
            self.assertEqual(open(os.path.join(root, "data", "labels.json"), "rb").read(), before)
        finally:
            shutil.rmtree(root)

    def test_two_sources_disagreeing_stop_the_build(self):
        root, cards = self.scratch()
        try:
            f = os.path.join(root, "intake", "scans", "bobloukas", "report.json")
            rep = json.load(open(f))
            p = next(p for p in rep["posts"] if (p.get("review") or {}).get("decision") == "add")
            p["review"]["side"] = "short" if p["review"]["side"] == "long" else "long"
            json.dump(rep, open(f, "w"))
            with self.assertRaisesRegex(lb.Conflict, "scan says add"):
                lb.derive(root, cards_path=cards, watch_dir=root)
        finally:
            shutil.rmtree(root)


class ScoreNeutral(unittest.TestCase):
    def test_ratings_are_the_served_ones(self):
        import build_chart
        served = json.load(open(os.path.join(HERE, "web", "data", "charts.json")))
        self.assertEqual(build_chart.build(os.path.join(HERE, "records"))["ratings"], served["ratings"])


if __name__ == "__main__":
    unittest.main()


class CodexReview(unittest.TestCase):
    """The four defects the implementation review reproduced, pinned."""
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-cr-")
        os.makedirs(os.path.join(self.root, "data"))
        for f in ("labels.json", "rules.json"):
            shutil.copy(os.path.join(HERE, "data", f), os.path.join(self.root, "data", f))
        self.rp, self.lp = os.path.join(self.root, "data", "rules.json"), os.path.join(self.root, "data", "labels.json")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_an_edited_label_switches_the_rules_off_even_with_its_old_pin(self):
        d = json.load(open(self.lp))
        l = next(x for x in d["labels"] if x["id"] == "2118181656398090718|NEST")
        l["owner"]["side"] = "short"                                                    # pin left as it was
        json.dump(d, open(self.lp, "w"))
        self.assertEqual(reader.kept_rules(self.rp, self.lp), [])
        for field, value in (("aliases", ["NOPE"]), ("multi", False), ("gating", False)):  # every gate input is bound
            d = json.load(open(os.path.join(HERE, "data", "labels.json")))
            next(x for x in d["labels"] if x["id"] == "2118181656398090718|NEST")[field] = value
            json.dump(d, open(self.lp, "w"))
            self.assertEqual(reader.kept_rules(self.rp, self.lp), [], field)

    def test_the_code_binding_covers_the_helpers_and_the_base_read(self):
        src = open(reader.__file__).read()
        tmp = os.path.join(self.root, "reader.py")
        open(tmp, "w").write(src.replace('return r"\\$?(?:"', 'return r"\\$*(?:"'))       # a change inside alias_re only
        real = reader.__file__
        try:
            reader.__file__ = tmp
            changed = reader.code_sha("more_cashtag")
        finally:
            reader.__file__ = real
        self.assertNotEqual(changed, reader.code_sha("more_cashtag"))

    def test_different_texts_stop_the_merge_and_a_cut_off_copy_does_not(self):
        root = tempfile.mkdtemp(prefix="quanty-txt-")
        try:
            for d in ("records", "intake"):
                shutil.copytree(os.path.join(HERE, d), os.path.join(root, d))
            cards = os.path.join(root, "cards.json")
            json.dump({"cards": {}}, open(cards, "w"))
            lb.derive(root, cards_path=cards, watch_dir=root)                            # the real scan copies are cut off / re-spaced: fine
            f = os.path.join(root, "intake", "scans", "bobloukas", "report.json")
            rep = json.load(open(f))
            p = next(p for p in rep["posts"] if p["id"] == "1993658195982876720")
            p["text"] = p["text"].replace("refueling", "top")
            json.dump(rep, open(f, "w"))
            with self.assertRaisesRegex(lb.Conflict, "different post texts"):
                lb.derive(root, cards_path=cards, watch_dir=root)
        finally:
            shutil.rmtree(root)

    def test_skip_reasons_need_explicit_no_side_words(self):
        self.assertIsNone(lb.skip_basis("Unconditional long, skipped because this is a repeat"))
        self.assertIsNone(lb.skip_basis("unconditional buyer here"))
        self.assertIsNone(lb.skip_basis("a conditional, but also a repeat of the last call"))
        self.assertEqual(lb.skip_basis("stocks in a decline phase: conditional, both directions"), "conditional")
        self.assertEqual(lb.skip_basis("'very mixed feeling on Bitcoin': no side"), "no side")
