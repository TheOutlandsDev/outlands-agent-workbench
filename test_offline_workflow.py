"""Owned offline-workflow regressions. Fake checks/engine receipts are unit data.

No real child, Bubblewrap check, Java process, network or model runs here. Full
actual acceptance belongs to the separate persistent QA/browser fixtures.
"""

import copy
import io
import json
import os
import signal
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import offline_workflow as workflow
import offline_workflow_worker as worker
from agent import Refused, canonical, sha, write_new


from test_offline_workflow_integration import seed_completed


class OfflineWorkflowTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)/"fixture";workflow.initialize(root);manager=workflow.WorkflowManager(root)
        self.addCleanup(manager.close);return root,manager

    def refused(self,operation,*args,**kwargs):
        with self.assertRaises(Refused) as caught:operation(*args,**kwargs)
        self.assertRegex(str(caught.exception),r"^OFFLINE_WORKFLOW_[A-Z_]+$")
        return str(caught.exception)

    def test_initialize_exact_private_source_and_read_only_validation(self):
        root,manager=self.fixture();before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        marker=workflow.validate_fixture(root)
        self.assertEqual(set(marker['files']),set(workflow.PROTECTED));self.assertEqual(manager.models,[])
        self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.assertEqual(root.stat().st_mode&0o777,0o700);self.assertEqual((root/'fixture.json').stat().st_mode&0o777,0o600)

    def test_existing_relative_overlap_and_linked_roots_refuse(self):
        root,manager=self.fixture();self.refused(workflow.initialize,root);self.refused(workflow.initialize,Path('relative'))
        self.refused(workflow.initialize,workflow.HERE/'nested');self.refused(workflow.initialize,workflow.HERE.parent)
        link=root.parent/'linked';link.symlink_to(root,target_is_directory=True);self.refused(workflow.validate_fixture,link)

    def test_changed_immutable_inputs_and_marker_shape_refuse(self):
        for name in workflow.PROTECTED:
            root,manager=self.fixture();path=root/name;path.write_bytes(path.read_bytes()+b'\n')
            self.refused(workflow.validate_fixture,root)
        root,manager=self.fixture();path=root/'fixture.json';value=json.loads(path.read_bytes());value['extra']=True;path.write_bytes(canonical(value))
        self.refused(workflow.validate_fixture,root)

    def test_source_mode_links_and_foreign_job_are_refused(self):
        for kind in ['mode','hardlink','symlink','foreign']:
            root,manager=self.fixture();source=root/'workspace/project/calculator.py'
            if kind=='mode':source.chmod(0o640)
            elif kind=='hardlink':os.link(source,root.parent/'other')
            elif kind=='symlink':source.rename(root.parent/'other');source.symlink_to(root.parent/'other')
            else:write_new(root/'workspace/data/jobs'/('f'*16+'.json'),b'{}')
            self.refused(workflow.validate_fixture,root)

    def test_invalid_request_consumes_one_claim_without_launch(self):
        root,manager=self.fixture()
        with patch('offline_workflow.REAL_POPEN',side_effect=AssertionError('real child')) as spawn:
            self.refused(manager.start,{'project':'arithmetic','model':'invented','goal':'invented'})
            claim=(root/'receipts/start-claim.json').read_bytes()
            self.refused(manager.start,{'project':'arithmetic','model':'scripted-demo','goal':manager.projects['arithmetic']['definition']['goal']})
            self.assertEqual(claim,(root/'receipts/start-claim.json').read_bytes());spawn.assert_not_called()

    def test_exact_guarded_spawn_failure_retains_failed_metadata_and_claim(self):
        root,manager=self.fixture();request={'project':'arithmetic','model':'scripted-demo','goal':manager.projects['arithmetic']['definition']['goal']}
        with patch('offline_workflow.REAL_POPEN',side_effect=OSError('invented private error')) as spawn:
            self.assertEqual(self.refused(manager.start,request),'OFFLINE_WORKFLOW_ENGINE_START_FAILED')
            self.assertEqual(spawn.call_count,1)
        self.assertEqual(json.loads(next((root/'workspace/data/jobs').glob('*.json')).read_bytes())['state'],'FAILED')
        self.refused(manager.start,request);self.assertFalse((root/'receipts/parent-started.json').exists())

    def test_argv_guard_rejects_model_extra_flags_and_nonexact_commands(self):
        root,manager=self.fixture();command=workflow.expected_command(root,'1'*16)
        for value in [command+['--allow-local-inference'],command[:-1]+['ollama'],command[3:],tuple(command)]:
            with patch('offline_workflow.REAL_POPEN',side_effect=AssertionError('real child')) as spawn:
                self.refused(manager._launch,value);spawn.assert_not_called()

    def test_fake_session_evidence_uses_actual_engine_plan_tool_and_result_shapes(self):
        root,manager=self.fixture();identifier,result=seed_completed(manager)
        report=workflow.python_report(root)
        self.assertEqual(report['id'],identifier);self.assertEqual(report['turns'],6)
        self.assertEqual((report['baseline_tests'],report['agent_tests'],report['final_tests']),(4,4,4))
        self.assertFalse(report['accepted']);self.assertFalse(report['ai_inference'])
        self.assertEqual(report['patch_sha256'],result['patch_sha256'])

    def test_export_requires_acceptance_and_patch_bytes_remain_exact(self):
        root,manager=self.fixture();identifier,result=seed_completed(manager)
        with self.assertRaises(Refused):manager.export(identifier)
        value=manager.view(identifier)
        manager.review({'id':identifier,'result_sha256':value['result_sha256'],'patch_sha256':value['patch_sha256'],'verdict':'accepted','note':'Invented unit acceptance'})
        exported=manager.export(identifier)
        self.assertTrue(workflow.python_report(root,exported,True)['accepted'])
        self.refused(workflow.python_report,root,exported+b'wrong',True)

    def test_terminal_restart_reads_same_records_without_new_child(self):
        root,manager=self.fixture();identifier,_=seed_completed(manager);before=workflow.python_report(root)
        manager.close()
        with patch('offline_workflow.REAL_POPEN',side_effect=AssertionError('new child')) as spawn:
            restarted=workflow.WorkflowManager(root);self.addCleanup(restarted.close)
            self.assertEqual(workflow.python_report(root),before);self.assertEqual(restarted.history()[0]['id'],identifier)
            self.refused(restarted.start,{'project':'arithmetic','model':'scripted-demo','goal':restarted.projects['arithmetic']['definition']['goal']});spawn.assert_not_called()

    def test_report_rejects_receipt_booleans_missing_start_and_metadata_identity_changes(self):
        for kind in ['bool','flags','start','meta-id','meta-source','log-mode','worker-lock','hold']:
            root,manager=self.fixture();identifier,_=seed_completed(manager)
            path=root/'receipts/worker-exit.json';value=json.loads(path.read_bytes())
            if kind=='bool':value['exit_code']=False;path.write_bytes(canonical(value))
            elif kind=='flags':value['python_level_guards']=False;path.write_bytes(canonical(value))
            elif kind=='start':(root/'receipts/worker-start.json').unlink()
            elif kind in ['meta-id','meta-source']:
                path=root/'workspace/data/jobs'/(identifier+'.json');value=json.loads(path.read_bytes());value['id' if kind=='meta-id' else 'source']='foreign';path.write_bytes(canonical(value))
            elif kind=='log-mode':(root/'workspace/data/jobs'/(identifier+'.log')).chmod(0o640)
            elif kind=='worker-lock':(root/'workspace/data/state/worker.lock').write_bytes(b'foreign')
            else:write_new(root/'workspace/data/state/hold.json',b'{}')
            self.refused(workflow.python_report,root)

    def test_event_and_candidate_drift_refuse_without_verifier_runtime_or_repairs(self):
        for kind in ['event','typed-tool','work','review']:
            root,manager=self.fixture();identifier,_=seed_completed(manager);run=root/'workspace/data/runs'/identifier
            if kind=='event':next(run.glob('event-*.json')).write_bytes(b'{}')
            elif kind=='typed-tool':
                path=next(path for path in run.glob('event-*.json') if json.loads(path.read_bytes()).get('kind')=='tool_result')
                value=json.loads(path.read_bytes());value['value']=[];path.write_bytes(canonical(value))
                # Only fabricated unit evidence: recreate the pre-terminal
                # state, never delete or retry a real/failed worker receipt.
                (root/'receipts/terminal.json').unlink()
                meta=json.loads((root/'workspace/data/jobs'/(identifier+'.json')).read_bytes())
                self.assertEqual(self.refused(manager.refresh,meta),'OFFLINE_WORKFLOW_RECORD')
                self.assertFalse((root/'receipts/terminal.json').exists())
            elif kind=='work':(run/'work/calculator.py').write_bytes(b'foreign\n')
            else:write_new(run/'review-000.json',canonical({'id':identifier,'verdict':'accepted','source_applied':True}))
            with patch('offline_workflow.WorkflowManager',side_effect=AssertionError('verifier runtime')),patch('workbench.process_stamp',side_effect=AssertionError('process probe')):
                self.refused(workflow.python_report,root,require_accepted=kind=='review')

    def test_directory_descriptor_is_closed_after_failed_mode_check(self):
        root,manager=self.fixture();root.chmod(0o750)
        original=os.close;closed=[];descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        with patch('offline_workflow.readiness_directory',return_value=descriptor),patch('offline_workflow.os.close',side_effect=lambda fd:(closed.append(fd),original(fd))[1]):self.refused(workflow._directory,root)
        self.assertEqual(closed,[descriptor]);root.chmod(0o700)

    def test_counter_schema_rejects_unknown_negative_and_boolean_values(self):
        root,manager=self.fixture()
        for counters in [{'unknown':0},{'start_requests':-1},{'start_requests':False}]:
            self.refused(workflow.offline_handler,manager,'invented','http://127.0.0.1:8765',counters)
        self.assertEqual(set(workflow.new_counters()),set(workflow.COUNTER_KEYS))

    def test_java_checks_are_once_only_separate_and_use_only_fixed_mocked_check(self):
        root,manager=self.fixture();before=manager.history()
        checked={'unit':{'exit_code':0,'tests_ran':1,'timed_out':False,'output_limited':False,'infrastructure_error':False,'kind':'java-main','phase':'run','output':'Invented unit Java check'}}
        with patch('offline_workflow.validate_jdk',return_value=Path('/invented/jdk')),patch('offline_workflow.fixed_checks',return_value=checked) as call:
            report=workflow.java_checks(root,Path('/invented/jdk'));self.assertFalse(report['java_agent_run']);self.assertFalse(report['model_inference']);self.assertEqual(call.call_count,1)
            self.refused(workflow.java_checks,root,Path('/invented/jdk'));self.assertEqual(call.call_count,1)
        self.assertEqual(manager.history(),before)

    def test_failed_java_check_receipt_and_claim_are_retained_without_retry(self):
        root,manager=self.fixture();checked={'unit':{'exit_code':1,'tests_ran':1,'timed_out':False,'output_limited':False,'infrastructure_error':False}}
        with patch('offline_workflow.validate_jdk',return_value=Path('/invented/jdk')),patch('offline_workflow.fixed_checks',return_value=checked) as call:
            self.refused(workflow.java_checks,root,Path('/invented/jdk'));self.assertTrue((root/'java/claim.json').exists());self.assertEqual(json.loads((root/'java/result.json').read_bytes())['checks'],checked)
            self.refused(workflow.java_checks,root,Path('/invented/jdk'));self.assertEqual(call.call_count,1)

    def test_worker_cli_installs_and_restores_production_sigterm_mapping(self):
        calls=[]
        with patch('offline_workflow_worker.signal.signal',side_effect=lambda sig,handler:(calls.append((sig,handler)),signal.SIG_DFL)[1]),patch('offline_workflow_worker.run_worker',return_value=0):
            self.assertEqual(worker.main(['--work-dir','/invented','--run-id','1'*16,'--','--backend','scripted-demo']),0)
        self.assertEqual([row[0] for row in calls],[signal.SIGTERM,signal.SIGTERM])
        with self.assertRaises(KeyboardInterrupt):calls[0][1](signal.SIGTERM,None)
        self.assertEqual(calls[1][1],signal.SIG_DFL)

    def test_child_guards_block_provider_dns_datagram_and_restore_with_strict_receipt(self):
        root,manager=self.fixture()
        class FakeChild:
            pid=os.getpid()
            returncode=None
            def poll(self):return self.returncode
            def terminate(self):self.returncode=1
            def kill(self):self.returncode=1
            def wait(self,timeout=None):self.returncode=1;return 1
        fake=FakeChild()
        with patch('offline_workflow.REAL_POPEN',return_value=fake),patch('workbench.process_stamp',return_value='invented-unit-stamp'):
            identifier=manager.start({'project':'arithmetic','model':'scripted-demo','goal':manager.projects['arithmetic']['definition']['goal']})['id']
        original_dns=socket.getaddrinfo
        def guarded_main(arguments):
            self.assertEqual(arguments,workflow.expected_command(root,identifier)[3:])
            for operation in [lambda:agent.Ollama.request(None,[],1),lambda:agent.Ollama.preflight(None),
                              lambda:socket.getaddrinfo('invented.invalid',80),lambda:socket.socket.connect(None,('invented.invalid',80)),
                              lambda:socket.socket.sendto(None,b'x',('invented.invalid',80))]:
                self.refused(operation)
            return 2
        with patch('offline_workflow_worker.agent.main',side_effect=guarded_main):
            self.assertEqual(worker.run_worker(root,identifier,workflow.expected_command(root,identifier)[3:]),2)
        receipt=json.loads((root/'receipts/worker-exit.json').read_bytes())
        self.assertEqual((receipt['provider_attempts'],receipt['network_attempts']),(2,3))
        self.assertEqual(receipt['exit_code'],2);self.assertIs(receipt['python_level_guards'],True);self.assertIs(receipt['os_wide_packet_audit'],False)
        self.assertIs(socket.getaddrinfo,original_dns)
        with patch('offline_workflow_worker.agent.main',side_effect=AssertionError('second engine invocation')) as call:
            self.refused(worker.run_worker,root,identifier,workflow.expected_command(root,identifier)[3:]);call.assert_not_called()

    def test_worker_waits_for_settled_parent_publication_without_consuming_attempt(self):
        root,manager=self.fixture();stage=root/'receipts/parent-started.json.next'
        write_new(stage,b'{}');os.link(stage,root/'receipts/parent-started.json')
        with patch('offline_workflow_worker.time.monotonic',side_effect=[0,11]),patch('offline_workflow_worker.time.sleep'),patch('offline_workflow_worker.agent.main',side_effect=AssertionError('premature engine')) as call:
            self.assertEqual(self.refused(worker.run_worker,root,'1'*16,workflow.expected_command(root,'1'*16)[3:]),'OFFLINE_WORKFLOW_PARENT_UNSETTLED');call.assert_not_called()
        self.assertTrue(stage.exists());self.assertFalse((root/'receipts/worker-start.json').exists())

    def test_close_is_idempotent_and_reports_inspection_failure_without_second_fd_close(self):
        root,manager=self.fixture()
        with patch('offline_workflow._runtime',side_effect=Refused('OFFLINE_WORKFLOW_STORE_UNSAFE')):
            manager.close()
        self.assertTrue(manager._closed);self.assertEqual(manager.shutdown_report['saved_state'],'NEEDS_INSPECTION')
        self.assertIs(manager.shutdown_report['acceptance_verified_by_shutdown'],False)
        with patch('workbench.Manager.close',side_effect=AssertionError('double close')):manager.close()


if __name__=='__main__':unittest.main()
