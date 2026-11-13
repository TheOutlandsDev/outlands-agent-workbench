"""Restricted HTTP boundary tests with fake checks and fabricated receipts.

These temporary fixtures never launch a worker or perform actual checks. Native
acceptance separately requires an earlier completed same-version real fixture.
"""

import copy
import json
import unittest
from unittest.mock import patch

from agent import Refused, canonical
import offline_workflow as workflow
from test_offline_workflow_integration import (
    memory_http, seed_completed, snapshot, start_request, workflow_fixture,
)
from test_saved_run_review_integration import review_guard


LIST_ROUTE = "/api/saved-review-history"
ENTRY_ROUTE = "/api/saved-review-history-entry"
OLD_COUNTERS = {"start_requests", "start_attempts", "worker_launches", "history_requests", "view_requests",
                "metadata_search_requests", "metadata_open_requests", "saved_review_requests", "review_requests",
                "export_requests", "parent_provider_attempts", "parent_outbound_attempts", "denied_requests"}
NEW_COUNTERS = {"saved_review_history_requests", "saved_review_history_entry_requests"}


def completed_context(manager):
    """Build only an explicitly fake unit history; no process or real checks."""
    identifier, _ = seed_completed(manager)
    view = manager.view(identifier)
    manager.review({"id":identifier, "result_sha256":view["result_sha256"], "patch_sha256":view["patch_sha256"],
                    "verdict":"accepted", "note":"Unit-only fake workflow receipt — café 🧪\x00\r\n<b>literal</b>"})
    request = memory_http(manager)
    status, searched = request("/api/run-history-search", {"query":identifier,"project":"","state":""})
    assert status == 200
    row = next(row for row in searched["runs"] if row["id"] == identifier)
    selected = {"id":identifier,"record_sha256":row["record_sha256"],"history_sha256":searched["history_sha256"]}
    status, review = request("/api/run-history-review", selected)
    assert status == 200 and review["decision"]["state"] == "ACCEPTED"
    pins = {key:review[key] for key in ["id","record_sha256","history_sha256","evidence_sha256"]}
    return identifier, request, review, pins


class CompleteReviewWorkflowBoundaryTests(unittest.TestCase):
    def test_exactly_two_finite_counters_added_and_initialized_independently(self):
        first, second = workflow.new_counters(), workflow.new_counters()
        self.assertEqual(set(first), OLD_COUNTERS | NEW_COUNTERS)
        self.assertEqual(len(first), len(workflow.COUNTER_KEYS))
        self.assertTrue(all(type(value) is int and value == 0 for value in first.values()))
        first["saved_review_history_requests"] = 1
        self.assertEqual(second["saved_review_history_requests"], 0)

    def test_restricted_routes_delegate_exact_pins_and_only_their_counters(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            identifier, request, review, pins = completed_context(manager)
            before, counters = snapshot(root), copy.deepcopy(manager.counters)
            with review_guard(manager):
                status, listed = request(LIST_ROUTE, pins)
                self.assertEqual(status, 200)
                status, detail = request(ENTRY_ROUTE, {**pins,"name":"review-000.json"})
                self.assertEqual(status, 200)
            self.assertEqual({k:listed[k] for k in pins},pins)
            self.assertEqual(detail["history"]["entry"]["note"],review["decision"]["receipt"]["note"])
            self.assertEqual(listed["history"]["entries"][0]["artifact_state"],"MATCHING")
            self.assertEqual(detail["history"]["current"],review["decision"]["current"])
            for counter in manager.counters:
                self.assertEqual(manager.counters[counter]-counters[counter],1 if counter in NEW_COUNTERS else 0)
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_normal_history_and_run_remain_real_and_new_routes_do_not_promote_decision(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            identifier, request, review, pins = completed_context(manager)
            before=snapshot(root)
            status, rows=request("/api/history",method="GET")
            self.assertEqual((status,rows[0]["id"],rows[0]["state"]),(200,identifier,"REVIEW_READY"))
            status, value=request("/api/run/"+identifier,method="GET")
            self.assertEqual(status,200);self.assertEqual(value["review"]["verdict"],"accepted")
            request(LIST_ROUTE,pins);request(ENTRY_ROUTE,{**pins,"name":"review-000.json"})
            status, after=request("/api/run-history-review",{key:pins[key] for key in pins if key!="evidence_sha256"})
            self.assertEqual((status,after),(200,review))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_non_whitelisted_and_similar_routes_still_refuse_without_delegation(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request=memory_http(manager);before=snapshot(root)
            with patch.object(manager,"saved_review_history",side_effect=AssertionError("unknown route delegated")),patch.object(
                    manager,"saved_review_history_entry",side_effect=AssertionError("unknown route delegated")):
                for route in [LIST_ROUTE+"/",LIST_ROUTE+"-other",ENTRY_ROUTE+"/",ENTRY_ROUTE+"-other",
                              "/api/project-setup","/api/snapshot-workspace-start","/api/task-preset-save"]:
                    status,value=request(route,{})
                    self.assertEqual((status,value["error"]),(409,"OFFLINE_WORKFLOW_ROUTE"))
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    status,value=request(route,method="GET")
                    self.assertEqual((status,value["error"]),(409,"OFFLINE_WORKFLOW_ROUTE"))
            self.assertEqual(manager.counters["denied_requests"],9)
            self.assertTrue(all(manager.counters[key]==0 for key in NEW_COUNTERS))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_auth_origin_host_and_cross_site_checks_precede_both_methods(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            with patch.object(manager,"saved_review_history",side_effect=AssertionError("auth reached list")),patch.object(
                    manager,"saved_review_history_entry",side_effect=AssertionError("auth reached detail")):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    value={**pins,**({"name":"review-000.json"} if route==ENTRY_ROUTE else {})}
                    for headers,expected in [({"Host":"foreign.invalid:8765"},403),
                                             ({"X-Workbench-Token":"wrong-token"},403),
                                             ({"Origin":"http://foreign.invalid"},409),
                                             ({"Sec-Fetch-Site":"cross-site"},403)]:
                        status,refusal=request(route,value,headers=headers)
                        self.assertEqual(status,expected)
                        self.assertIn("error",refusal)
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_duplicate_headers_transfer_encoding_and_bad_lengths_precede_methods(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            invalid=[[('Content-Type','application/json')],[('Content-Length','1')],
                     {'Transfer-Encoding':'chunked'},{'Content-Type':'text/plain'},
                     {'Content-Length':'-1'},{'Content-Length':'1.0'},{'Content-Length':'0'},
                     {'Content-Length':'99999999999'},{'Content-Length':'32769'}]
            with patch.object(manager,"saved_review_history",side_effect=AssertionError("framing reached list")),patch.object(
                    manager,"saved_review_history_entry",side_effect=AssertionError("framing reached detail")):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    for headers in invalid:
                        status,value=request(route,pins,headers=headers)
                        self.assertEqual((status,value['error']),(409,'OFFLINE_WORKFLOW_HTTP_INPUT'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_short_declared_body_is_rejected_before_any_method(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager)
            with patch.object(manager,"saved_review_history",side_effect=AssertionError("short body reached list")),patch.object(
                    manager,"saved_review_history_entry",side_effect=AssertionError("short body reached detail")):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    status,value=request(route,pins,headers={'Content-Length':'9999'})
                    self.assertEqual((status,value['error']),(409,'OFFLINE_WORKFLOW_HTTP_INPUT'))
            spawn.assert_not_called()

    def test_exact_request_byte_cap_accepts_valid_padded_json_and_refuses_overflow(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            for route in [LIST_ROUTE,ENTRY_ROUTE]:
                value={**pins,**({'name':'review-000.json'} if route==ENTRY_ROUTE else {})}
                raw=canonical(value);padded=raw+b' '*(32768-len(raw))
                with review_guard(manager):
                    status,result=request(route,raw=padded)
                    self.assertEqual(status,200)
                status,result=request(route,raw=padded+b' ')
                self.assertEqual((status,result['error']),(409,'OFFLINE_WORKFLOW_HTTP_INPUT'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_production_exact_request_schema_is_preserved_before_store_reads(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            invalid=[None,[],{}, {k:v for k,v in pins.items() if k!='evidence_sha256'},
                     {**pins,'override':True},{**pins,'id':pins['id']+'\n'},
                     {**pins,'record_sha256':pins['record_sha256']+'\u2028'}]
            with patch.object(manager,'_run_history_inspection',side_effect=AssertionError('invalid request read jobs')),patch.object(
                    manager,'_saved_run_review_inspection',side_effect=AssertionError('invalid request read evidence')):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    for item in invalid:
                        status,value=request(route,item)
                        self.assertEqual((status,value['error']),(409,'SAVED_REVIEW_INPUT'))
                for item in [{**pins,'name':'review-000.json'}, {**pins,'name':None},
                             {**pins,'name':'review-100.json'}, {**pins,'name':'review-000.json\r'}]:
                    route=LIST_ROUTE if item['name']=='review-000.json' else ENTRY_ROUTE
                    status,value=request(route,item)
                    self.assertEqual((status,value['error']),(409,'SAVED_REVIEW_INPUT'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_duplicate_json_keys_invalid_utf8_and_truncated_json_refuse(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            request=memory_http(manager);before=snapshot(root)
            with patch.object(manager,'_run_history_inspection',side_effect=AssertionError('bad JSON read jobs')):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    for raw in [b'{"id":"a","id":"b"}',b'\xff',b'{"id":',b'NaN']:
                        status,value=request(route,raw=raw)
                        self.assertEqual((status,value['error']),(409,'SAVED_REVIEW_INPUT'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_stale_evidence_and_unknown_selection_do_not_fallback_or_write(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            with review_guard(manager):
                for route in [LIST_ROUTE,ENTRY_ROUTE]:
                    value={**pins,'evidence_sha256':'0'*64,**({'name':'review-000.json'} if route==ENTRY_ROUTE else {})}
                    status,refusal=request(route,value)
                    self.assertEqual((status,refusal['error']),(409,'SAVED_REVIEW_EVIDENCE_CHANGED'))
                status,refusal=request(ENTRY_ROUTE,{**pins,'name':'review-099.json'})
                self.assertEqual((status,refusal['error']),(409,'SAVED_REVIEW_NOT_FOUND'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_complete_response_cap_is_still_enforced_by_original_controller(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            for route,reducer in [(LIST_ROUTE,'summarize_review_history'),(ENTRY_ROUTE,'inspect_review_history_entry')]:
                value={**pins,**({'name':'review-000.json'} if route==ENTRY_ROUTE else {})}
                with patch('workbench.'+reducer,return_value={'invented':'x'*65536}):
                    status,refusal=request(route,value)
                    self.assertEqual((status,refusal['error']),(409,'SAVED_REVIEW_OUTPUT_LIMIT'))
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()

    def test_new_finite_counter_values_validate_without_accepting_foreign_fields(self):
        with workflow_fixture() as (root, manager, marker, spawn):
            for counters in [{key:False for key in NEW_COUNTERS},{key:-1 for key in NEW_COUNTERS},
                             {'foreign_counter':0},{'saved_review_history_requests':'0'}]:
                with self.assertRaisesRegex(Refused,'^OFFLINE_WORKFLOW_COUNTERS$'):
                    workflow.offline_handler(manager,'unit-token','http://127.0.0.1:8765',counters)
            counters={key:3 for key in NEW_COUNTERS}
            workflow.offline_handler(manager,'unit-token','http://127.0.0.1:8765',counters)
            self.assertEqual(set(counters),OLD_COUNTERS|NEW_COUNTERS)
            self.assertTrue(all(counters[key]==3 for key in NEW_COUNTERS));spawn.assert_not_called()

    def test_existing_once_only_admission_and_parent_provider_guards_remain_effective(self):
        import agent
        import http.client
        with workflow_fixture() as (root, manager, marker, spawn):
            _,request,review,pins=completed_context(manager);before=snapshot(root)
            with self.assertRaisesRegex(Refused,'^OFFLINE_WORKFLOW_ALREADY_ATTEMPTED$'):
                manager.start(start_request(manager))
            with workflow.parent_guards(manager,'http://127.0.0.1:8765'):
                with self.assertRaisesRegex(Refused,'^OFFLINE_WORKFLOW_PROVIDER_REFUSED$'):
                    agent.Ollama.request(None,[])
                with self.assertRaisesRegex(Refused,'^OFFLINE_WORKFLOW_NETWORK_REFUSED$'):
                    http.client.HTTPConnection('invalid.example',9).connect()
            self.assertEqual(manager.counters['parent_provider_attempts'],1)
            self.assertEqual(manager.counters['parent_outbound_attempts'],1)
            self.assertEqual(before,snapshot(root));spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
