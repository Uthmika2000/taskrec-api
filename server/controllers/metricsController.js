const metricsService = require('../services/metricsService');
const handleError = require('../utils/handleError');

exports.getWorkload = async (req, res, next) => {
  try {
    const data = await metricsService.getWorkload(req.params.sprintId);
    res.json({ success: true, data });
  } catch (error) { handleError(error, res, next); }
};

exports.getAccuracy = async (req, res, next) => {
  try {
    const data = await metricsService.getAccuracy();
    res.json({ success: true, data });
  } catch (error) { handleError(error, res, next); }
};

exports.getEvaluation = async (req, res, next) => {
  try {
    const data = await metricsService.getEvaluation();
    res.json({ success: true, data });
  } catch (error) { handleError(error, res, next); }
};
