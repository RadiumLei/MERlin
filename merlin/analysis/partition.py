import pandas
import numpy as np

from merlin.core import analysistask
from merlin.util import spatialfeature
from merlin.util import barcodedb

class PartitionBarcodes(analysistask.ParallelAnalysisTask):

    """
    An analysis task that assigns RNAs and sequential signals to cells
    based on the boundaries determined during the segment task.
    """

    def __init__(self, dataSet, parameters=None, analysisName=None):
        super().__init__(dataSet, parameters, analysisName)

    def fragment_count(self):
        return len(self.dataSet.get_fovs())

    def get_estimated_memory(self):
        return 2048

    def get_estimated_time(self):
        return 1

    def get_dependencies(self):
        return [self.parameters['filter_task'],
                self.parameters['assignment_task'],
                self.parameters['alignment_task']]
    
    def get_barcode_database(self) -> barcodedb.BarcodeDB:
        """ Get the barcode database this analysis task saves barcodes into.

        Returns: The barcode database reference.
        """
        return barcodedb.PyTablesBarcodeDB(self.dataSet, self)
        
    def get_partitioned_barcodes(self, fov: int = None) -> pandas.DataFrame:
        """Retrieve the cell by barcode matrixes calculated from this
        analysis task.

        Args:
            fov: the fov to get the barcode table for. If not specified, the
                combined table for all fovs are returned.

        Returns:
            A pandas data frame containing the parsed barcode information.
        """
        if fov is None:
            return pandas.concat(
                [self.get_partitioned_barcodes(fov)
                 for fov in self.dataSet.get_fovs()]
            )

        return self.dataSet.load_dataframe_from_csv(
            'counts_per_cell', self.get_analysis_name(), fov, index_col=0)

    def _run_analysis(self, fragmentIndex):
        filterTask = self.dataSet.load_analysis_task(
            self.parameters['filter_task'])
        assignmentTask = self.dataSet.load_analysis_task(
            self.parameters['assignment_task'])
        alignTask = self.dataSet.load_analysis_task(
            self.parameters['alignment_task'])
        
        if "write_barcodes" not in self.parameters:
            self.parameters["write_barcodes"] = False

        fovBoxes = alignTask.get_fov_boxes()
        fovIntersections = sorted([i for i, x in enumerate(fovBoxes) if
                                   fovBoxes[fragmentIndex].intersects(x)])

        codebook = filterTask.get_codebook()
        barcodeCount = codebook.get_barcode_count()

        bcDB = filterTask.get_barcode_database()
        for fi in fovIntersections:
            partialBC = bcDB.get_barcodes(fi)
            if fi == fovIntersections[0]:
                currentFOVBarcodes = partialBC.copy(deep=True)
            else:
                currentFOVBarcodes = pandas.concat(
                    [currentFOVBarcodes, partialBC], 0)

        currentFOVBarcodes = currentFOVBarcodes.reset_index().copy(deep=True)
        
        sDB = assignmentTask.get_feature_database()
        currentCells = sDB.read_features(fragmentIndex)

        countsDF = pandas.DataFrame(
            data=np.zeros((len(currentCells), barcodeCount)),
            columns=range(barcodeCount),
            index=[x.get_feature_id() for x in currentCells])
        
        # this is necessay because the old MERlin force cell_index to be an
        # integer np.int64. This will make it comptiable with previous 
        # merlin decoding results
        currentFOVBarcodes.cell_index = \
            currentFOVBarcodes.cell_index.astype(str)    
        
        for cell in currentCells:
            # change contains_positions to contains_positions_global_z
            # which allows barcode partition based on the global z
            # coordinates rather than z Index. Z indedx can be confusing
            # and requires segmentation images to be the same with 
            # barcode images, sometime this may not be true
            contained = cell.contains_positions_global_z(
                    currentFOVBarcodes.loc[:,['global_x', 'global_y',
                                             'global_z']].values)
            
            if True in contained:
                currentFOVBarcodes.loc[contained, "cell_index"] = \
                    cell.get_feature_id()
            count = currentFOVBarcodes[contained].groupby('barcode_id').size()
            count = count.reindex(range(barcodeCount), fill_value=0)
            countsDF.loc[cell.get_feature_id(), :] = count.values.tolist()

        barcodeNames = [codebook.get_name_for_barcode_index(x)
                        for x in countsDF.columns.values.tolist()]
        countsDF.columns = barcodeNames

        self.dataSet.save_dataframe_to_csv(
                countsDF, 'counts_per_cell', self.get_analysis_name(),
                fragmentIndex)
       
        if self.parameters["write_barcodes"]:
            bcDatabase = self.get_barcode_database()
            bcDatabase.write_barcodes(currentFOVBarcodes, 
                                  fov=fragmentIndex)
        
class ExportPartitionedBarcodes(analysistask.AnalysisTask):

    """
    An analysis task that combines counts per cells data from each
    field of view into a single output file.
    """

    def __init__(self, dataSet, parameters=None, analysisName=None):
        super().__init__(dataSet, parameters, analysisName)

    def get_estimated_memory(self):
        return 2048

    def get_estimated_time(self):
        return 5

    def get_dependencies(self):
        return [self.parameters['partition_task']]

    def _run_analysis(self):
        pTask = self.dataSet.load_analysis_task(
                    self.parameters['partition_task'])
        parsedBarcodes = pTask.get_partitioned_barcodes()

        self.dataSet.save_dataframe_to_csv(
                    parsedBarcodes, 'barcodes_per_feature',
                    self.get_analysis_name())
