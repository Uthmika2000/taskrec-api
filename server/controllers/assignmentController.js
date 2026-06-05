const assignmentService = require('../services/assignmentService');

function handleError(error, res, next) {
  if (error.statusCode) return res.status(error.statusCode).json({ success: false, message: error.message });
  next(error);
}

exports.listAssignments = async (req, res, next) => {
  try {
    const assignments = await assignmentService.listAssignments(req.query);
    res.json({ success: true, data: assignments });
  } catch (error) { handleError(error, res, next); }
};

exports.getAssignment = async (req, res, next) => {
  try {
    const assignment = await assignmentService.getAssignment(req.params.id);
    res.json({ success: true, data: assignment });
  } catch (error) { handleError(error, res, next); }
};
