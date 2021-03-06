from unittest import TestCase
from unittest.mock import Mock, patch, call
from calrissian.job import k8s_safe_name, KubernetesVolumeBuilder, VolumeBuilderException, KubernetesPodBuilder
from calrissian.job import CalrissianCommandLineJob, KubernetesPodVolumeInspector


class SafeNameTestCase(TestCase):

    def setUp(self):
        self.unsafe_name = 'Wine_1234'
        self.safe_name = 'wine-1234'

    def test_makes_name_safe(self):
        made_safe = k8s_safe_name(self.unsafe_name)
        self.assertEqual(self.safe_name, made_safe)


class KubernetesPodVolumeInspectorTestCase(TestCase):
    def test_first_container_with_one_container(self):
        mock_pod = Mock()
        mock_pod.spec.containers = ['somecontainer']
        kpod = KubernetesPodVolumeInspector(mock_pod)
        container = kpod.get_first_container()
        self.assertEqual(container, 'somecontainer')

    def test_first_container_with_two_container(self):
        mock_pod = Mock()
        mock_pod.spec.containers = ['container1', 'container2']
        kpod = KubernetesPodVolumeInspector(mock_pod)
        container = kpod.get_first_container()
        self.assertEqual(container, 'container1')

    def test_get_persistent_volumes_dict(self):
        mock_pod = Mock()
        kpod = KubernetesPodVolumeInspector(mock_pod)
        mock_data1_volume = Mock()
        mock_data1_volume.name = 'data1'
        mock_data1_volume.persistent_volume_claim = Mock(claim_name='data1-claim-name')
        mock_data2_volume = Mock()
        mock_data2_volume.name = 'data2'
        mock_data2_volume.persistent_volume_claim = Mock(claim_name='data2-claim-name')

        mock_ignored_volume = Mock(persistent_volume_claim=Mock())
        mock_pod.spec.volumes = [mock_data1_volume, mock_data2_volume]
        expected_dict = {
            'data1': 'data1-claim-name',
            'data2': 'data2-claim-name',
        }
        self.assertEqual(kpod.get_persistent_volumes_dict(), expected_dict)

    def test_get_mounted_persistent_volumes(self):
        mock_pod = Mock()
        mock_volume_mount1 = Mock()
        mock_volume_mount1.name = 'data1'
        mock_volume_mount1.mount_path = '/data/one'
        mock_volume_mount1.sub_path = None
        mock_volume_mount2 = Mock()
        mock_volume_mount2.name = 'data2'
        mock_volume_mount2.mount_path = '/data/two'
        mock_volume_mount2.sub_path = '/basedir'
        mock_pod.spec.containers = [
            Mock(volume_mounts=[mock_volume_mount1, mock_volume_mount2])
        ]
        kpod = KubernetesPodVolumeInspector(mock_pod)
        kpod.get_persistent_volumes_dict = Mock()
        kpod.get_persistent_volumes_dict.return_value = {'data1': 'data1-claim', 'data2': 'data2-claim'}
        mp_volumes = kpod.get_mounted_persistent_volumes()

        self.assertEqual(mp_volumes, [('/data/one', None, 'data1-claim'), ('/data/two', '/basedir', 'data2-claim')])

    def test_get_mounted_persistent_volumes_ignores_unmounted_volumes(self):
        mock_pod = Mock()
        mock_volume_mount1 = Mock()
        mock_volume_mount1.name = 'data1'
        mock_volume_mount1.mount_path = '/data/one'
        mock_volume_mount1.sub_path = None
        mock_volume_mount2 = Mock()
        mock_volume_mount2.name = 'data2'
        mock_volume_mount2.mount_path = '/data/two'
        mock_volume_mount2.sub_path = 'basedir'
        mock_pod.spec.containers = [
            Mock(volume_mounts=[mock_volume_mount1, mock_volume_mount2])
        ]
        kpod = KubernetesPodVolumeInspector(mock_pod)
        kpod.get_persistent_volumes_dict = Mock()
        kpod.get_persistent_volumes_dict.return_value = {'data1': 'data1-claim'}
        mp_volumes = kpod.get_mounted_persistent_volumes()

        self.assertEqual(mp_volumes, [('/data/one', None, 'data1-claim')])


class KubernetesVolumeBuilderTestCase(TestCase):

    def setUp(self):
        self.volume_builder = KubernetesVolumeBuilder()

    def test_finds_persistent_volume(self):
        self.volume_builder.add_persistent_volume_entry('/prefix/1', None, 'claim1')
        self.assertIsNotNone(self.volume_builder.find_persistent_volume('/prefix/1f'))
        self.assertIsNone(self.volume_builder.find_persistent_volume('/notfound'))

    def test_calculates_subpath(self):
        subpath = KubernetesVolumeBuilder.calculate_subpath('/prefix/1/foo', '/prefix/1', None)
        self.assertEqual('foo', subpath)

    def test_calculates_subpath_with_parent_subpath(self):
        subpath = KubernetesVolumeBuilder.calculate_subpath('/prefix/1/foo', '/prefix/1', 'basedir')
        self.assertEqual('basedir/foo', subpath)

    def test_random_tag(self):
        random_tag = KubernetesVolumeBuilder.random_tag(8)
        self.assertEqual(len(random_tag), 8)

    def test_add_rw_volume_binding(self):
        self.assertEqual(0, len(self.volume_builder.volumes))
        self.volume_builder.add_persistent_volume_entry('/prefix/1', None, 'claim1')
        self.assertEqual({'name':'claim1', 'persistentVolumeClaim': {'claimName': 'claim1'}}, self.volume_builder.volumes[0])

        self.assertEqual(0, len(self.volume_builder.volume_mounts))
        self.volume_builder.add_volume_binding('/prefix/1/input1', '/input1-target', True)
        self.assertEqual({'name': 'claim1', 'mountPath': '/input1-target', 'readOnly': False, 'subPath': 'input1'}, self.volume_builder.volume_mounts[0])

    def test_add_ro_volume_binding(self):
        # read-only
        self.assertEqual(0, len(self.volume_builder.volumes))
        self.volume_builder.add_persistent_volume_entry('/prefix/2', None, 'claim2')
        self.assertEqual({'name':'claim2', 'persistentVolumeClaim': {'claimName': 'claim2'}}, self.volume_builder.volumes[0])

        self.assertEqual(0, len(self.volume_builder.volume_mounts))
        self.volume_builder.add_volume_binding('/prefix/2/input2', '/input2-target', False)
        self.assertEqual({'name': 'claim2', 'mountPath': '/input2-target', 'readOnly': True, 'subPath': 'input2'}, self.volume_builder.volume_mounts[0])

    def test_volume_binding_exception_if_not_found(self):
        self.assertEqual(0, len(self.volume_builder.volumes))
        with self.assertRaises(VolumeBuilderException) as context:
            self.volume_builder.add_volume_binding('/prefix/2/input2', '/input2-target', False)
        self.assertIn('Could not find a persistent volume', str(context.exception))

    @patch('calrissian.job.KubernetesPodVolumeInspector')
    def test_add_persistent_volume_entries_from_pod(self, mock_kubernetes_pod_inspector):
        mock_kubernetes_pod_inspector.return_value.get_mounted_persistent_volumes.return_value = [
            ('/tmp/data1', None, 'data1-claim'),
            ('/tmp/data2', '/basedir', 'data2-claim'),
        ]

        self.volume_builder.add_persistent_volume_entries_from_pod('some-pod-data')

        pv_entries = self.volume_builder.persistent_volume_entries
        self.assertEqual(pv_entries.keys(), set(['/tmp/data1', '/tmp/data2']))
        expected_entry1 = {
            'prefix': '/tmp/data1',
            'subPath': None,
            'volume': {
                'name': 'data1-claim',
                'persistentVolumeClaim': {
                    'claimName': 'data1-claim'
                }
            }
        }
        expected_entry2 = {
            'prefix': '/tmp/data2',
            'subPath': '/basedir',
            'volume': {
                'name': 'data2-claim',
                'persistentVolumeClaim': {
                    'claimName': 'data2-claim'
                }
            }
        }
        self.assertEqual(pv_entries['/tmp/data1'], expected_entry1)
        self.assertEqual(pv_entries['/tmp/data2'], expected_entry2)
        volumes = self.volume_builder.volumes
        self.assertEqual(len(volumes), 2)
        self.assertEqual(volumes[0], expected_entry1['volume'])
        self.assertEqual(volumes[1], expected_entry2['volume'])


class KubernetesPodBuilderTestCase(TestCase):

    def setUp(self):
        self.name = 'PodName'
        self.container_image = 'dockerimage:1.0'
        self.environment = {'K1':'V1', 'K2':'V2', 'HOME': '/homedir'}
        self.volume_mounts = [Mock(), Mock()]
        self.volumes = [Mock()]
        self.command_line = ['cat']
        self.stdout = 'stdout.txt'
        self.stderr = 'stderr.txt'
        self.stdin = 'stdin.txt'
        self.resources = {'coresMin': 1, 'ramMin': 1024}
        self.pod_builder = KubernetesPodBuilder(self.name, self.container_image, self.environment, self.volume_mounts,
                                                self.volumes, self.command_line, self.stdout, self.stderr, self.stdin,
                                                self.resources)

    def test_safe_pod_name(self):
        self.assertEqual('podname-pod', self.pod_builder.pod_name())

    def test_safe_container_name(self):
        self.assertEqual('podname-container', self.pod_builder.container_name())

    def test_container_command(self):
        self.assertEqual(['/bin/sh', '-c'], self.pod_builder.container_command())

    def test_container_args_without_redirects(self):
        # container_args returns a list with a single item since it is passed to 'sh', '-c'
        self.pod_builder.stdout = None
        self.pod_builder.stderr = None
        self.pod_builder.stdin = None
        self.assertEqual(['cat'], self.pod_builder.container_args())

    def test_container_args_with_redirects(self):
        self.assertEqual(['cat > stdout.txt 2> stderr.txt < stdin.txt'], self.pod_builder.container_args())

    def test_container_environment(self):
        environment = self.pod_builder.container_environment()
        self.assertEqual(len(self.environment), len(environment))
        self.assertIn({'name': 'K1', 'value': 'V1'}, environment)
        self.assertIn({'name': 'K2', 'value': 'V2'}, environment)
        self.assertIn({'name': 'HOME', 'value': '/homedir'}, environment)

    def test_container_workingdir(self):
        workingdir = self.pod_builder.container_workingdir()
        self.assertEqual('/homedir', workingdir)

    def test_resource_bound(self):
        self.assertEqual('requests', KubernetesPodBuilder.resource_bound('coresMin'))
        self.assertEqual('limits', KubernetesPodBuilder.resource_bound('ramMax'))
        self.assertEqual('limits', KubernetesPodBuilder.resource_bound('outdirMax'))
        self.assertEqual(None, KubernetesPodBuilder.resource_bound('coresMid'))

    def test_resource_type(self):
        self.assertEqual('cpu', KubernetesPodBuilder.resource_type('coresMin'))
        self.assertEqual('memory', KubernetesPodBuilder.resource_type('ramMax'))
        self.assertEqual(None, KubernetesPodBuilder.resource_type('outdirMax'))
        self.assertEqual('cpu', KubernetesPodBuilder.resource_type('coresMid'))

    def test_resource_value(self):
        self.assertEqual('3Mi', KubernetesPodBuilder.resource_value('memory', 3))
        self.assertEqual('4', KubernetesPodBuilder.resource_value('cpu', 4))
        self.assertEqual(None, KubernetesPodBuilder.resource_value('outdir', 62))

    def test_container_resources(self):
        self.pod_builder.resources = {'coresMin': 2, 'ramMin': 256, 'coresMax': 4}
        resources = self.pod_builder.container_resources()
        expected = {
            'limits': {
                'cpu': '4',
            },
            'requests': {
                'cpu': '2',
                'memory': '256Mi'
            }
        }
        self.assertEqual(expected, resources)

    def test_build(self):
        expected = {
            'metadata': {
                'name': 'podname-pod'
            },
            'apiVersion': 'v1',
            'kind':'Pod',
            'spec': {
                'containers': [
                    {
                        'name': 'podname-container',
                        'image': 'dockerimage:1.0',
                        'command': ['/bin/sh', '-c'],
                        'args': ['cat > stdout.txt 2> stderr.txt < stdin.txt'],
                        'env': [
                            {'name': 'HOME', 'value': '/homedir'},
                            {'name': 'K1', 'value': 'V1'},
                            {'name': 'K2', 'value': 'V2'},
                        ],
                        'resources': {
                            'requests': {
                                'cpu': '1',
                                'memory': '1024Mi',
                            }
                        },
                        'volumeMounts': self.volume_mounts,
                        'workingDir': '/homedir',
                     }
                ],
                'restartPolicy': 'Never',
                'volumes': self.volumes
            }
        }
        self.assertEqual(expected, self.pod_builder.build())


@patch('calrissian.job.KubernetesClient')
@patch('calrissian.job.KubernetesVolumeBuilder')
class CalrissianCommandLineJobTestCase(TestCase):

    def setUp(self):
        self.builder = Mock(outdir='/out')
        self.joborder = Mock()
        self.make_path_mapper = Mock()
        self.requirements = [{'class': 'DockerRequirement', 'dockerPull': 'dockerimage:1.0'}]
        self.hints = []
        self.name = 'test-clj'

    def make_job(self):
        return CalrissianCommandLineJob(self.builder, self.joborder, self.make_path_mapper, self.requirements,
                                       self.hints, self.name)

    def test_constructor_calculates_persistent_volume_entries(self, mock_volume_builder, mock_client):
        job = self.make_job()
        mock_volume_builder.return_value.add_persistent_volume_entries_from_pod.assert_called_with(
            mock_client.return_value.get_current_pod.return_value
        )

    @patch('calrissian.job.os')
    def test_makes_tmpdir_when_not_exists(self, mock_os, mock_volume_builder, mock_client):
        mock_os.path.exists.return_value = False
        job = self.make_job()
        job.make_tmpdir()
        self.assertTrue(mock_os.path.exists.called)
        self.assertTrue(mock_os.makedirs.called_with(job.tmpdir))

    @patch('calrissian.job.os')
    def test_not_make_tmpdir_when_exists(self, mock_os, mock_volume_builder, mock_client):
        mock_os.path.exists.return_value = True
        job = self.make_job()
        job.make_tmpdir()
        self.assertTrue(mock_os.path.exists.called)
        self.assertFalse(mock_os.makedirs.called)

    def test_populate_env_vars(self, mock_volume_builder, mock_client):
        job = self.make_job()
        job.populate_env_vars()
        # tmpdir should be '/tmp'
        self.assertEqual(job.environment['TMPDIR'], '/tmp')
        # home should be builder.outdir
        self.assertEqual(job.environment['HOME'], '/out')

    def test_wait_for_kubernetes_pod(self, mock_volume_builder, mock_client):
        job = self.make_job()
        job.wait_for_kubernetes_pod()
        self.assertTrue(mock_client.return_value.wait_for_completion.called)

    def test_finish_calls_output_callback_with_status(self, mock_volume_builder, mock_client):
        job = self.make_job()
        mock_collected_outputs = Mock()
        job.collect_outputs = Mock()
        job.collect_outputs.return_value = mock_collected_outputs
        job.output_callback = Mock()
        job.finish(0) # 0 = exit success
        self.assertTrue(job.collect_outputs.called)
        job.output_callback.assert_called_with(mock_collected_outputs, 'success')

    def test_finish_looks_up_codes(self, mock_volume_builder, mock_client):
        job = self.make_job()
        mock_collected_outputs = Mock()
        job.collect_outputs = Mock()
        job.collect_outputs.return_value = mock_collected_outputs
        job.output_callback = Mock()

        job.successCodes = [1,] # Also 0
        job.temporaryFailCodes = [2,]
        job.permanentFailCodes = [3,] # also anything not covered
        expected_codes = {
            0: 'success',
            1: 'success',
            2: 'temporaryFail',
            3: 'permanentFail',
            4: 'permanentFail',
            -1: 'permanentFail'
        }
        for code, status in expected_codes.items():
            job.finish(code)
            job.output_callback.assert_called_with(mock_collected_outputs, status)

    def test__get_container_image(self, mock_volume_builder, mock_client):
        job = self.make_job()
        image = job._get_container_image()
        self.assertEqual(image, 'dockerimage:1.0')

    @patch('calrissian.job.KubernetesPodBuilder')
    @patch('calrissian.job.os')
    def test_create_kubernetes_runtime(self, mock_os, mock_pod_builder, mock_volume_builder, mock_client):
        def realpath(path):
            return '/real' + path
        mock_os.path.realpath = realpath
        mock_add_volume_binding = Mock()
        mock_volume_builder.return_value.add_volume_binding = mock_add_volume_binding

        mock_pod_builder.return_value.build.return_value = '<built pod>'
        job = self.make_job()
        job.outdir = '/outdir'
        job.tmpdir = '/tmpdir'
        mock_runtime_context = Mock(tmpdir_prefix='TP')
        built = job.create_kubernetes_runtime(mock_runtime_context)
        # Adds volume binding for outdir
        # Adds volume binding for /tmp
        self.assertEqual(mock_add_volume_binding.call_args_list,
                         [call('/real/outdir', '/out', True),
                          call('/real/tmpdir', '/tmp', True)])
        # looks at generatemapper
        # creates a KubernetesPodBuilder
        self.assertEqual(mock_pod_builder.call_args, call(
            job.name,
            job._get_container_image(),
            job.environment,
            job.volume_builder.volume_mounts,
            job.volume_builder.volumes,
            job.command_line,
            job.stdout,
            job.stderr,
            job.stdin,
            job.builder.resources
        ))
        # calls builder.build
        # returns that
        self.assertTrue(mock_pod_builder.return_value.build.called)
        self.assertEqual(built, mock_pod_builder.return_value.build.return_value)

    def test_execute_kubernetes_pod(self, mock_volume_builder, mock_client):
        job = self.make_job()
        k8s_pod = Mock()
        job.execute_kubernetes_pod(k8s_pod)
        self.assertTrue(mock_client.return_value.submit_pod.called_with(k8s_pod))

    def test_add_file_or_directory_volume_ro(self, mock_volume_builder, mock_client):
        mock_add_volume_binding = mock_volume_builder.return_value.add_volume_binding
        job = self.make_job()
        runtime = []
        volume = Mock(resolved='/resolved', target='/target')
        job.add_file_or_directory_volume(runtime, volume, None)
        # It should add the volume binding with writable=False
        self.assertEqual(mock_add_volume_binding.call_args, call('/resolved', '/target', False))

    def test_ignores_add_file_or_directory_volume_with_under_colon(self, mock_volume_builder, mock_client):
        mock_add_volume_binding = mock_volume_builder.return_value.add_volume_binding
        job = self.make_job()
        runtime = []
        volume = Mock(resolved='_:/resolved', target='/target')
        job.add_file_or_directory_volume(runtime, volume, None)
        self.assertFalse(mock_add_volume_binding.called)

    def test_add_writable_file_volume_inplace(self, mock_volume_builder, mock_client):
        mock_add_volume_binding = mock_volume_builder.return_value.add_volume_binding
        job = self.make_job()
        job.inplace_update = True
        runtime = []
        volume = Mock(resolved='/resolved', target='/target')
        job.add_writable_file_volume(runtime, volume, None, None)
        # with inplace, the binding should be added with writable=True
        self.assertEqual(mock_add_volume_binding.call_args, call('/resolved', '/target', True))

    @patch('calrissian.job.shutil')
    @patch('calrissian.job.ensure_writable')
    def test_add_writable_file_volume_host_outdir_tgt(self, mock_ensure_writable, mock_shutil, mock_volume_builder, mock_client):
        mock_shutil.copy = Mock()
        mock_add_volume_binding = mock_volume_builder.return_value.add_volume_binding
        job = self.make_job()
        runtime = []
        volume = Mock(resolved='/resolved', target='/target')
        # In this case, the target is a host outdir, so we do not add a volume mapping
        # but instead just copy the file there and ensure it is writable
        job.add_writable_file_volume(runtime, volume, '/host-outdir-tgt', None)
        self.assertFalse(mock_add_volume_binding.called)
        self.assertEqual(mock_shutil.copy.call_args, call('/resolved', '/host-outdir-tgt'))
        self.assertEqual(mock_ensure_writable.call_args, call('/host-outdir-tgt'))

    @patch('calrissian.job.tempfile')
    @patch('calrissian.job.shutil')
    @patch('calrissian.job.ensure_writable')
    def test_add_writable_file_volumehost_not_outdir_tgt(self, mock_ensure_writable, mock_shutil, mock_tempfile, mock_volume_builder, mock_client):
        mock_shutil.copy = Mock()
        mock_tempfile.mkdtemp.return_value = '/mkdtemp-dir'
        mock_add_volume_binding = mock_volume_builder.return_value.add_volume_binding
        job = self.make_job()
        runtime = []
        volume = Mock(resolved='/resolved', target='/target')
        job.add_writable_file_volume(runtime, volume, None, None)
        # When writable but not inplace, we expect a copy
        # And when not host-outdir-tgt, we expect that copy in a tmpdir
        self.assertEqual(mock_tempfile.mkdtemp.call_args, call(dir=job.tmpdir))
        self.assertEqual(mock_shutil.copy.call_args, call('/resolved', '/mkdtemp-dir/resolved'))
        # and we expect add_volume_binding called with the tempdir copy
        self.assertEqual(mock_add_volume_binding.call_args, call('/mkdtemp-dir/resolved', '/target', True))
        # We also expect ensure_writable to be called on the copy in mkdtemp-dir
        self.assertEqual(mock_ensure_writable.call_args, call('/mkdtemp-dir/resolved'))

    def test_add_writable_directory_volume(self, mock_volume_builder, mock_client):
        # These were ported over from cwltool but are not used by our workflows
        # and can be tested later
        pass

    def test_run(self, mock_volume_builder, mock_client):
        job = self.make_job()
        job.make_tmpdir = Mock()
        job.populate_env_vars = Mock()
        job._setup = Mock()
        job.create_kubernetes_runtime = Mock()
        job.execute_kubernetes_pod = Mock()
        job.wait_for_kubernetes_pod = Mock()
        job.finish = Mock()

        runtimeContext = Mock()
        job.run(runtimeContext)
        self.assertTrue(job.make_tmpdir.called)
        self.assertTrue(job.populate_env_vars.called)
        self.assertEqual(job._setup.call_args, call(runtimeContext))
        self.assertEqual(job.create_kubernetes_runtime.call_args, call(runtimeContext))
        self.assertEqual(job.execute_kubernetes_pod.call_args, call(job.create_kubernetes_runtime.return_value))
        self.assertTrue(job.wait_for_kubernetes_pod.called)
        self.assertEqual(job.finish.call_args, call(job.wait_for_kubernetes_pod.return_value))
